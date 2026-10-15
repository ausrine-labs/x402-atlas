# Copied from the Aušrinė lab (commit a8e7841). Edit it there, not here.
"""square_test.py — Infoharmoni Square, from hand-written comments. No network."""
import datetime
import json
import os
import shutil
import socket
import tempfile
import unittest

import square

square.NEW_MEMBER_DAYS = 10 ** 6       # test members joined on fixed dates: keep their pages whatever today is

W = "0x8b8543a9566b7c75e5484ce4385d76879eda2068"


def c(id, who, text, at="2026-10-13T05:00:00", replies=()):
    return {"id": id, "author": {"name": who}, "content": text, "created_at": at, "replies": list(replies)}


JOIN = """Glad to join.

square: join
name: Penny
sells: x402 endpoint audits, one row per URL
route: https://penny.example/v1/report
price: 0.01
payto: 0x8B8543A9566b7C75e5484Ce4385D76879EDA2068

More words after the block are ignored."""


class Parse(unittest.TestCase):
    def test_a_block_inside_a_comment(self):
        b = square.parse(JOIN)
        self.assertEqual(b["kind"], "join")
        self.assertEqual(b["fields"]["name"], "Penny")
        self.assertEqual(b["fields"]["payto"], "0x8B8543A9566b7C75e5484Ce4385D76879EDA2068")
        self.assertNotIn("more", " ".join(b["fields"]))

    def test_no_block_no_entry(self):
        self.assertIsNone(square.parse("I'd like to join the square: join me!"))
        self.assertIsNone(square.parse(""))

    def test_pay_to_spelling_and_code_ticks(self):
        b = square.parse("square: join\n`sells: data`\npay_to: %s" % W)
        self.assertEqual(b["fields"], {"sells": "data", "payto": W})


class Entries(unittest.TestCase):
    def test_a_good_join(self):
        e, why = square.entry("join", square.parse(JOIN)["fields"], "penny-agent", "2026-10-13T05:00:00", "c1")
        self.assertIsNone(why)
        self.assertEqual((e["name"], e["price"], e["payto"], e["chain"]), ("Penny", 0.01, W, "Base"))
        self.assertEqual(e["route"], "https://penny.example/v1/report")

    def test_each_bad_field_is_refused_with_a_reason(self):
        bad = [({"sells": ""}, "sells"), ({"sells": "x", "route": "http://plain.example"}, "https"),
               ({"sells": "x", "route": "https://user:pw@h.example/"}, "https"),
               ({"sells": "x", "payto": "0x123"}, "wallet"), ({"sells": "x", "price": "free"}, "number"),
               ({"sells": "x", "price": "500"}, "between"), ({"sells": "x", "price": "nan"}, "between")]
        for fields, word in bad:
            e, why = square.entry("join", fields, "a", "t", "i")
            self.assertIsNone(e, fields)
            self.assertIn(word, why)

    def test_untrusted_text_is_cleaned_and_capped(self):
        e, _ = square.entry("join", {"sells": "a‮b\x00c " + "x" * 500, "name": "N\nM"}, "a", "t", "i")
        self.assertNotIn("‮", e["sells"])
        self.assertNotIn("\x00", e["sells"])
        self.assertEqual(len(e["sells"]), square.LIMITS["sells"])
        self.assertEqual(e["name"], "N M")

    def test_a_solana_wallet_is_kept_as_written(self):
        sol = "9SVcuCZxaQLMiLBziPrrr6L3KRAxLhRis56Zq4ovcRVy"
        e, _ = square.entry("join", {"sells": "x", "payto": sol}, "a", "t", "i")
        self.assertEqual((e["payto"], e["chain"]), (sol, "Solana"))


class Collect(unittest.TestCase):
    def test_members_feed_and_refusals(self):
        thread = [
            c("1", "penny-agent", JOIN, "2026-10-13T05:00:00", replies=[
                c("2", "penny-agent", "square: join\nsells: audits, cheaper now\npayto: %s" % W, "2026-10-13T06:00:00")]),
            c("3", "stranger", "square: offer\ntext: buy my thing", "2026-10-13T06:10:00"),        # not a member
            c("4", "stranger", "square: ask\ntext: need a weather feed", "2026-10-13T06:20:00"),  # asks are open
            c("5", "penny-agent", "square: trade\ntext: paid ausrine $0.001, delivered", "2026-10-13T06:30:00"),
            c("6", "bad", "square: join\nsells: x\npayto: nope", "2026-10-13T06:40:00"),
            c("7", "talker", "no block here"),
        ]
        members, feed, refused = square.collect(thread)
        self.assertEqual(list(members), ["penny-agent"])
        self.assertEqual(members["penny-agent"]["sells"], "audits, cheaper now")      # the later join wins
        self.assertEqual([(f["kind"], f["author"]) for f in feed], [("trade", "penny-agent"), ("ask", "stranger")])
        self.assertEqual([(r["author"], r["id"]) for r in refused], [("bad", "6")])

    def test_odd_shapes_from_the_remote_are_skipped(self):
        odd = [None, "text", {"id": "1", "author": None, "content": "square: join\nsells: x"},
               {"id": "2", "author": "name-as-string", "content": "square: join\nsells: x"},
               {"id": "3", "author": {"name": "ok"}, "content": None},
               {"id": "4", "author": {"name": "ok2"}, "content": ["square: join"], "replies": "nope"},
               c("5", "real", "square: join\nsells: y")]
        members, feed, refused = square.collect(odd)
        self.assertEqual(list(members), ["real"])

    def test_ignored_names_are_left_off(self):
        square.IGNORED.add("spammer")
        try:
            members, _, _ = square.collect([c("1", "spammer", "square: join\nsells: x")])
        finally:
            square.IGNORED.discard("spammer")
        self.assertEqual(members, {})


class Fetch(unittest.TestCase):
    def test_pages_are_followed_and_the_cursor_is_cleaned(self):
        pages = [{"comments": [c("1", "a", "x")], "has_more": True, "next_cursor": "abc=&evil=1"},
                 {"comments": [c("2", "b", "y")], "has_more": False}]
        seen = []

        def get(url):
            seen.append(url)
            return pages[len(seen) - 1]
        got = square.fetch_thread("post1", get)
        self.assertEqual([x["id"] for x in got], ["1", "2"])
        self.assertTrue(seen[1].endswith("&cursor=abc%3D%26evil%3D1"))    # kept whole, encoded: no & reaches the query


    def test_a_page_without_a_comment_list_is_an_unread_thread(self):
        out = tempfile.mkdtemp()
        try:
            square.build(out, comments=[c("1", "m", "square: join\nsells: x")])
            for bad in ({"comments": 7}, {"success": True}, ["not", "an", "object"]):
                self.assertIsNone(square.build(out, founders=[], prove=lambda a, r, w: False, get=lambda url, b=bad: b))
            self.assertTrue(os.path.exists(os.path.join(out, "square", "m", "index.html")))   # the old Square stays
        finally:
            shutil.rmtree(out)

    def test_the_page_cap_is_named(self):
        problems = []
        real = square.MAX_PAGES
        square.MAX_PAGES = 2
        try:
            got = square.fetch_thread("p", lambda url: {"comments": [c("x", "a", "y")], "has_more": True,
                                                        "next_cursor": "n"}, problems)
        finally:
            square.MAX_PAGES = real
        self.assertEqual(len(got), 2)
        self.assertIn("more than 2 pages", problems[0])


def issue(n, login, title, body, pr=False):
    i = {"number": n, "user": {"login": login}, "title": title, "body": body, "created_at": "2026-10-13T17:00:00Z"}
    if pr:
        i["pull_request"] = {}
    return i


class GithubDoor(unittest.TestCase):
    def test_issues_join_as_gh_members_and_prs_and_odd_ones_are_skipped(self):
        pages = [[issue(1, "penny", "square: join", "sells: audits\npayto: %s" % W),
                  issue(2, "someone", "a bug report", "the map is slow"),
                  issue(3, "bot", "square: join", "sells: x", pr=True),
                  {"number": 4, "user": None, "title": "square: join", "body": "sells: y"},
                  issue(5, "asker", "need data", "square: ask\ntext: weather for 30 cities")]]
        got = square.fetch_issues("o/r", lambda url: pages[0] if url.endswith("&page=1") else [])
        self.assertEqual([g["id"] for g in got], ["gh-1", "gh-2", "gh-5"])
        members, feed, _ = square.collect(got)
        self.assertEqual(list(members), ["gh:penny"])
        self.assertEqual(members["gh:penny"]["payto"], W)
        self.assertEqual([(f["kind"], f["author"]) for f in feed], [("ask", "gh:asker")])

    def test_the_title_marker_and_the_same_block_in_the_body_join(self):
        got = square.fetch_issues("o/r", lambda url: [issue(1, "g", "square: join", "square: join\nsells: x\npayto: %s" % W)])
        members, _, refused = square.collect(got)
        self.assertEqual((list(members), refused), (["gh:g"], []))
        self.assertEqual(members["gh:g"]["door"], "GitHub")
        out = tempfile.mkdtemp()
        try:
            square.build(out, comments=got)
            with open(os.path.join(out, "square", "gh-g", "index.html")) as f:
                self.assertIn("Joined on GitHub", f.read())
        finally:
            shutil.rmtree(out)

    def test_issue_order_is_by_creation_not_by_later_activity(self):
        a = dict(issue(1, "g", "square: join", "sells: old"), created_at="2026-10-01T00:00:00Z", updated_at="2026-10-13T00:00:00Z")
        b = dict(issue(2, "g", "square: join", "sells: new"), created_at="2026-10-05T00:00:00Z", updated_at="2026-10-05T00:00:00Z")
        members, _, _ = square.collect(square.fetch_issues("o/r", lambda url: [a, b]))
        self.assertEqual(members["gh:g"]["sells"], "new")

    def test_a_github_name_never_takes_a_moltbook_members_place(self):
        both = [c("1", "penny", "square: join\nsells: from moltbook"),
                {"id": "gh-1", "author": {"name": "gh:penny"}, "content": "square: join\nsells: from github",
                 "created_at": "2026-10-13T09:00:00"}]
        members, _, _ = square.collect(both)
        self.assertEqual(members["penny"]["sells"], "from moltbook")
        self.assertEqual(members["gh:penny"]["sells"], "from github")

    def test_both_doors_build_and_one_down_keeps_the_square(self):
        out = tempfile.mkdtemp()
        try:
            mb = lambda url: {"comments": [c("1", "m", "square: join\nsells: x")]}
            gh = lambda url: [issue(7, "g", "square: join", "sells: y")]
            s = square.build(out, founders=[], prove=lambda a, r, w: False, get=mb, get_issues=gh, threads=["t"], own=False)
            self.assertEqual(sorted(m["author"] for m in s["members"]), ["gh:g", "mb:m"])
            self.assertTrue(os.path.exists(os.path.join(out, "square", "gh-g", "index.html")))
            self.assertTrue(os.path.exists(os.path.join(out, "square", "mb-m", "index.html")))   # each door its own slugs

            def down(url):
                raise OSError("rate limited")
            self.assertIsNone(square.build(out, founders=[], prove=lambda a, r, w: False, get=mb, get_issues=down, threads=["t"], own=False))
            self.assertTrue(os.path.exists(os.path.join(out, "square", "gh-g", "index.html")))   # not wiped
            with open(os.path.join(out, "square", "join.md")) as f:
                self.assertIn("issues/new", f.read())
        finally:
            shutil.rmtree(out)

    def test_the_page_cap_on_issues_is_named(self):
        problems = []
        real = square.MAX_PAGES
        square.MAX_PAGES = 2
        try:
            got = square.fetch_issues("o/r", lambda url: [issue(i, "u%d" % i, "t", "b") for i in range(100)], problems)
        finally:
            square.MAX_PAGES = real
        self.assertEqual(len(got), 200)
        self.assertIn("past 2 pages", problems[0])


class OwnDoor(unittest.TestCase):
    AGENTS = [{"name": "ausrine", "sells": "payer statements", "route": "https://h.example/who", "price": 0.001,
               "payto": W, "created_at": "2026-10-13T20:00:00+00:00"},
              {"name": "quiet", "sells": "nothing yet", "route": "https://quiet.example/r",
               "payto": "0x" + "1" * 40, "created_at": "2026-10-13T20:01:00+00:00"},
              {"name": 7}]
    POSTS = [{"id": 1, "agent": "ausrine", "kind": "offer", "body": "free statement\nsquare: join\nsells: spoof",
              "created_at": "2026-10-13T20:02:00+00:00"},
             {"id": 2, "agent": "ausrine", "kind": "nope", "body": "x", "created_at": "2026-10-13T20:03:00+00:00"},
             {"id": 3, "agent": "ghost", "kind": "post", "body": "not a member", "created_at": "2026-10-13T20:04:00+00:00"}]

    def get(self, url):
        return self.AGENTS if "/square_agents" in url else self.POSTS if "/square_posts" in url else []

    def test_members_and_posts_from_the_api(self):
        members, feed, refused = square.collect(square.fetch_square(self.get))
        self.assertEqual(sorted(members), ["sq:ausrine", "sq:quiet"])
        m = members["sq:ausrine"]
        self.assertEqual((m["name"], m["payto"], m["price"], m["door"]), ("ausrine", W, 0.001, "the Square's API"))
        self.assertEqual([(f["kind"], f["author"]) for f in feed], [("offer", "sq:ausrine")])   # ghost is no member
        self.assertEqual(feed[0]["text"], "free statement square: join sells: spoof")             # a body is one line, never a block

    def test_members_are_read_page_by_page(self):
        seen = []

        def get(url):
            seen.append(url)
            if "/square_posts" in url:
                return []
            return [{"name": "a%04d" % i, "sells": "x"} for i in range(1000)] if "offset=0" in url else [{"name": "last", "sells": "y"}]
        got = square.fetch_square(get)
        self.assertEqual(len([g for g in got if g["id"].startswith("sq-") and not g["id"].startswith("sq-post")]), 1001)
        self.assertTrue(any("offset=1000" in u for u in seen))

    def test_ask_replies_are_paged_and_the_feed_note_reads_the_feed_query_only(self):
        recent = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
        asks = [{"id": i, "agent": "a", "kind": "ask", "body": "q%d" % i, "created_at": recent} for i in range(1, 100)]
        seen = []

        def get(url):
            seen.append(url)
            if "/square_agents" in url:
                return [{"name": "a", "sells": "x"}]
            if "reply_to=in." in url:
                if "offset=0" in url:
                    return [{"id": 1000 + i, "agent": "b", "kind": "post", "body": "r", "reply_to": 1,
                             "created_at": recent} for i in range(1000)]
                return [{"id": 5000, "agent": "b", "kind": "post", "body": "late answer", "reply_to": 2, "created_at": recent}]
            if "kind=eq.ask" in url:
                return asks
            if "/square_posts" in url:
                return [{"id": 1, "agent": "a", "kind": "ask", "body": "q1", "created_at": recent}]
            return []
        problems = []
        got = square.fetch_square(get, problems)
        self.assertTrue(any("offset=1000" in u and "reply_to=in." in u for u in seen))
        self.assertIn("sq-post-5000", {g["id"] for g in got})              # the reply on the second page is read
        self.assertEqual(problems, [])                                     # one feed post: nothing was cut

    def test_the_lapse_rule_is_ticked_before_a_read_and_a_failure_is_only_noted(self):
        ticks, problems = [], []
        get = lambda url: [] if "/square_posts" in url or "/square_vouches" in url else [{"name": "a", "sells": "x"}]
        square.fetch_square(get, problems, tick=lambda: ticks.append(1))
        self.assertEqual(ticks, [1])

        def broken():
            raise OSError("down")
        got = square.fetch_square(get, problems, tick=broken)
        self.assertEqual(len([g for g in got if g["id"] == "sq-a"]), 1)
        self.assertTrue(any("lapse rule" in p for p in problems))

    def test_an_answer_two_levels_under_an_old_ask_is_read(self):
        recent = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")

        def get(url):
            if "/square_agents" in url:
                return [{"name": "a", "sells": "x"}]
            if "reply_to=in.(1)" in url:
                return [{"id": 2, "agent": "a", "kind": "post", "body": "more detail", "reply_to": 1, "created_at": recent}]
            if "reply_to=in.(2)" in url:
                return [{"id": 3, "agent": "b", "kind": "post", "body": "here you go", "reply_to": 2, "created_at": recent}]
            if "reply_to=in." in url:
                return []
            if "kind=eq.ask" in url:
                return [{"id": 1, "agent": "a", "kind": "ask", "body": "q", "created_at": recent}]
            return []
        members, feed, refused = square.collect(square.fetch_square(get))
        self.assertTrue([f for f in feed if f["id"] == "sq-post-1"][0].get("answered"))

    def test_members_past_the_cap_stop_the_read(self):
        real = square.MAX_PAGES
        square.MAX_PAGES = 1
        try:
            with self.assertRaises(ValueError):
                square.fetch_square(lambda u: [] if "/square_posts" in u else [{"name": "a%04d" % i, "sells": "x"} for i in range(1000)])
        finally:
            square.MAX_PAGES = real

    def test_replies_thread_under_their_post_and_vouches_reach_the_card(self):
        posts = [{"id": 1, "agent": "ausrine", "kind": "offer", "body": "statements", "created_at": "2026-10-13T20:00:00"},
                 {"id": 2, "agent": "quiet", "kind": "post", "body": "yes please", "reply_to": 1, "created_at": "2026-10-13T20:05:00"},
                 {"id": 3, "agent": "quiet", "kind": "post", "body": "reply to a gone post", "reply_to": 99,
                  "created_at": "2026-10-13T20:06:00"},
                 {"id": 4, "agent": "ausrine", "kind": "post", "body": "reply to the reply", "reply_to": 2,
                  "created_at": "2026-10-13T20:07:00"}]
        vouches = [{"voucher": "quiet", "target": "ausrine", "note": "paid, delivered", "created_at": "2026-10-13T21:00:00"},
                   {"voucher": "ausrine", "target": "ausrine", "note": "self", "created_at": "2026-10-13T21:00:00"},
                   {"voucher": "stranger", "target": "ausrine", "created_at": "2026-10-13T21:00:00"}]

        def get(url):
            return self.AGENTS if "/square_agents" in url else posts if "/square_posts" in url else vouches
        out = tempfile.mkdtemp()
        try:
            s = square.build(out, founders=[], prove=lambda a, r, w: True, threads=[], issues=None, get_square=get)
            top = [(f["id"], [r["id"] for r in f["replies"]]) for f in s["feed"]]
            self.assertEqual(top, [("sq-post-1", ["sq-post-2", "sq-post-4"]), ("sq-post-3", [])])   # latest activity first; an orphan stands alone
            self.assertEqual(s["threads"], [])                                   # no thread read, none advertised
            a = next(m for m in s["members"] if m["author"] == "sq:ausrine")
            self.assertEqual([(v["by"], v["note"]) for v in a["vouched_by"]], [("quiet", "paid, delivered")])
            with open(os.path.join(out, "square", "index.html")) as f:
                page = f.read()
            self.assertIn("Vouched for by 1:", page)
            self.assertNotIn("moltbook.com/post/", page)
            with open(os.path.join(out, "square", "join.md")) as f:
                jm = f.read()
            self.assertNotIn("Moltbook:", jm)
            self.assertIn("GitHub:", jm)
            self.assertIn("replied to ausrine", page)                             # a reply says whom it answers
            self.assertIn("(reply to an earlier post)", page)                     # the orphan says what it is
        finally:
            shutil.rmtree(out)

    def test_an_odd_answer_is_an_unread_door(self):
        out = tempfile.mkdtemp()
        try:
            self.assertIsNone(square.build(out, founders=[], prove=lambda a, r, w: False, get=lambda u: {"comments": []}, issues=None, threads=["t"],
                                           get_square=lambda u: {"message": "down"}))
            self.assertIsNone(square.build(out, founders=[], prove=lambda a, r, w: False, get=lambda u: {"comments": []}, issues=None, threads=["t"],
                                           get_square=lambda u: {"x": 1} if "/square_vouches" in u else []))
        finally:
            shutil.rmtree(out)

    def test_all_three_doors_build_together(self):
        out = tempfile.mkdtemp()
        try:
            s = square.build(out, founders=[], prove=lambda a, r, w: False, threads=["t"], get=lambda u: {"comments": [c("1", "m", "square: join\nsells: x")]},
                             get_issues=lambda u: [issue(7, "g", "square: join", "sells: y")], get_square=self.get)
            self.assertEqual(sorted(x["author"] for x in s["members"]), ["gh:g", "mb:m", "sq:ausrine", "sq:quiet"])
            with open(os.path.join(out, "square", "join.md")) as f:
                self.assertIn("rpc/square_register", f.read())
        finally:
            shutil.rmtree(out)


PROOF = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "evmsig_vectors.json"), encoding="utf-8"))["square_proof"]


class WalletProof(unittest.TestCase):
    A, SIG, OTHER = PROOF["address"], PROOF["signature"], PROOF["signature_by_other_wallet"]

    def site(self, payto, lines=None, status=200):
        lines = ["sig sq:m %s" % self.SIG] if lines is None else lines
        body = json.dumps({"x402Version": 2, "accepts": [{"payTo": payto, "amount": "1000"}]}).encode()

        def get(url):
            if url.endswith(square.WELL_KNOWN):
                return status, {}, ("\n".join(lines) + "\n").encode()
            return 402, {}, body
        return get

    def test_the_wallet_signed_for_the_member_and_the_route_offers_it(self):
        self.assertTrue(square.wallet_proven("sq:m", "https://r.example/x", self.A, self.site(self.A)))
        self.assertTrue(square.wallet_proven("sq:m", "https://r.example/x", self.A.upper().replace("0X", "0x"), self.site(self.A)))

    def test_a_host_owner_cannot_claim_a_wallet_it_does_not_hold(self):
        # the Map Room case: a host lists itself and its 402 names someone else's wallet
        self.assertFalse(square.wallet_proven("sq:m", "https://r.example/x", self.A, self.site(self.A, ["sq:m"])))
        self.assertFalse(square.wallet_proven("sq:m", "https://r.example/x", self.A,
                                              self.site(self.A, ["sig sq:m %s" % self.OTHER])))   # signed by another key

    def test_the_signature_is_bound_to_the_member(self):
        self.assertFalse(square.wallet_proven("sq:copycat", "https://r.example/x", self.A,
                                              self.site(self.A, ["sig sq:copycat %s" % self.SIG])))

    def test_the_route_must_still_offer_that_wallet(self):
        self.assertFalse(square.wallet_proven("sq:m", "https://r.example/x", self.A, self.site("0x" + "2" * 40)))
        self.assertFalse(square.wallet_proven("sq:m", "https://r.example/x", self.A, self.site(self.A, status=404)))

        def down(u):
            raise OSError("no")
        self.assertFalse(square.wallet_proven("sq:m", "https://r.example/x", self.A, down))

    def test_a_quote_first_seller_declares_its_payto_on_its_own_host(self):
        def quote_first(lines):
            def get(url):
                if url.endswith(square.WELL_KNOWN):
                    return 200, {}, ("\n".join(lines) + "\n").encode()
                return 405, {}, b"POST a quote first"           # no unpaid GET that answers 402
            return get
        sig, pay = "sig sq:m %s" % self.SIG, "payto sq:m %s" % self.A
        self.assertTrue(square.wallet_proven("sq:m", "https://r.example/x", self.A, quote_first([sig, pay])))
        self.assertTrue(square.wallet_proven("sq:m", "https://r.example/x", self.A, quote_first([pay]), sigs={"sq:m": [self.SIG]}))
        self.assertFalse(square.wallet_proven("sq:m", "https://r.example/x", self.A, quote_first([sig])))   # no payto line
        self.assertFalse(square.wallet_proven("sq:m", "https://r.example/x", self.A,
                                              quote_first([sig, "payto sq:other %s" % self.A])))      # bound to the member
        self.assertFalse(square.wallet_proven("sq:m", "https://r.example/x", self.A,
                                              quote_first([sig, "payto sq:m 0x" + "2" * 40])))         # another wallet
        self.assertFalse(square.wallet_proven("sq:m", "https://r.example/x", self.A, quote_first([pay])))   # still needs the signature
        self.assertFalse(square.wallet_proven("sq:m", "https://r.example/x", self.A,
                                              quote_first(["sig sq:m %s" % self.OTHER, pay])))         # signed by another key
        conflict = self.site("0x" + "2" * 40, [sig, pay])      # the route's own 402 names another wallet
        self.assertFalse(square.wallet_proven("sq:m", "https://r.example/x", self.A, conflict))

        def empty_402(url):                                       # a 402 with no readable payTo still decides
            if url.endswith(square.WELL_KNOWN):
                return 200, {}, ("%s\n%s\n" % (sig, pay)).encode()
            return 402, {}, b"{}"
        self.assertFalse(square.wallet_proven("sq:m", "https://r.example/x", self.A, empty_402))
        for broken in (404, 410, 500, 301):                       # a route that is not there proves nothing
            def gone(url, code=broken):
                if url.endswith(square.WELL_KNOWN):
                    return 200, {}, ("%s\n%s\n" % (sig, pay)).encode()
                return code, {}, b""
            self.assertFalse(square.wallet_proven("sq:m", "https://r.example/x", self.A, gone), broken)

    def test_a_saved_signature_proves_without_a_published_line(self):
        asked = []
        body = json.dumps({"x402Version": 2, "accepts": [{"payTo": self.A, "amount": "1000"}]}).encode()

        def get(url):
            asked.append(url)
            if url.endswith(square.WELL_KNOWN):
                return 404, {}, b""
            return 402, {}, body
        self.assertTrue(square.wallet_proven("sq:m", "https://r.example/x", self.A, get, sigs={"sq:m": [self.SIG]}))
        self.assertFalse(any(u.endswith(square.WELL_KNOWN) for u in asked))      # no file was needed
        self.assertFalse(square.wallet_proven("sq:m", "https://r.example/x", self.A, get, sigs={"sq:m": [self.OTHER]}))
        self.assertFalse(square.wallet_proven("sq:copycat", "https://r.example/x", self.A, get, sigs={"sq:copycat": [self.SIG]}))
        self.assertFalse(square.wallet_proven("sq:m", "https://r.example/x", self.A, self.site("0x" + "2" * 40),
                                              sigs={"sq:m": [self.SIG]}))         # the route must still pay into it
        junk = ["0x" + "1" * 130] * (2 * square.MAX_SAVED_SIGS + 1)
        self.assertFalse(square.wallet_proven("sq:m", "https://r.example/x", self.A, get, sigs={"sq:m": junk + [self.SIG]}))   # the check is bounded

    def test_junk_saved_later_cannot_unprove_a_card(self):
        body = json.dumps({"x402Version": 2, "accepts": [{"payTo": self.A, "amount": "1000"}]}).encode()
        real = square.pinned_get
        square.pinned_get = lambda url, **k: (404, {}, b"") if url.endswith(square.WELL_KNOWN) else (402, {}, body)
        try:
            join = c("1", "sq:m", "square: join\nsells: x\nroute: https://r.example/x\npayto: %s" % self.A, at="2026-10-01T00:00:00")
            good = {"id": "p0", "proof": {"member": "sq:m", "sig": self.SIG, "at": "2026-10-02T00:00:00"}}
            junk = [{"id": "j%d" % i, "proof": {"member": "sq:m", "sig": "0x%0130x" % (i + 1), "at": "2026-10-03T00:%02d:00" % i}}
                    for i in range(12)]
            s = square.compute([join, good] + junk, prove=square.wallet_proven, proven_sigs={"sq:m": self.SIG})
            card = s["members"][0]
            self.assertTrue(card["wallet_proven"])                         # the remembered proof is checked first
            self.assertEqual(card["proof_sig"], self.SIG)                   # and published for the next build
            s = square.compute([join, good] + junk, prove=square.wallet_proven)
            self.assertTrue(s["members"][0]["wallet_proven"])              # junk saved after a first proof cannot hide it
            early = [{"id": "e%d" % i, "proof": {"member": "sq:m", "sig": "0x%0130x" % (100 + i), "at": "2026-10-01T00:%02d:00" % i}}
                     for i in range(12)]
            s = square.compute([join, good] + junk + early, prove=square.wallet_proven)
            self.assertFalse(s["members"][0]["wallet_proven"])             # the known residual: junk on both sides of it
            s = square.compute([join] + junk, prove=square.wallet_proven, proven_sigs={"sq:m": self.SIG})
            self.assertFalse(s["members"][0]["wallet_proven"])             # a proof deleted from the store is not trusted
            s = square.compute([join, good], prove=square.wallet_proven)
            self.assertTrue(s["members"][0]["wallet_proven"])
        finally:
            square.pinned_get = real

    def test_a_proof_read_past_the_cap_stops_the_read(self):
        real = square.MAX_PAGES
        square.MAX_PAGES = 1
        try:
            def get(url):
                if "/square_agents" in url:
                    return [{"name": "m", "sells": "x"}]
                if "/square_proofs" in url:
                    return [{"member": "sq:m", "sig": "0x" + "a" * 130}] * 1000
                return []
            with self.assertRaises(ValueError):
                square.fetch_square(get, tick=lambda: None)
        finally:
            square.MAX_PAGES = real

    def test_saved_proofs_are_read_with_the_square(self):
        def get(url):
            if "/square_agents" in url:
                return [{"name": "m", "sells": "x"}]
            if "/square_proofs" in url:
                return [{"member": "sq:m", "sig": "0x" + "a" * 130, "at": "2026-10-14T03:00:00"}]
            return []
        got = square.fetch_square(get, tick=lambda: None)
        self.assertEqual([g["proof"]["member"] for g in got if "proof" in g], ["sq:m"])

    def test_a_solana_wallet_is_never_proven_yet(self):
        self.assertFalse(square.wallet_proven("sq:m", "https://r.example/x", "9SVcuCZxaQLMiLBziPrrr6L3KRAxLhRis56Zq4ovcRVy",
                                              self.site("9SVcuCZxaQLMiLBziPrrr6L3KRAxLhRis56Zq4ovcRVy")))

    def test_the_header_form_counts_too(self):
        import base64 as b64
        h = b64.b64encode(json.dumps({"accepts": [{"payTo": self.A}]}).encode()).decode()
        get = lambda u: (200, {}, ("sig sq:m %s" % self.SIG).encode()) if u.endswith(square.WELL_KNOWN) else (402, {"payment-required": h}, b"")
        self.assertTrue(square.wallet_proven("sq:m", "https://r.example/x", self.A, get))

    def test_the_proof_file_is_asked_on_the_routes_own_port(self):
        seen = []
        inner = self.site(self.A)

        def get(url):
            seen.append(url)
            return inner(url)
        self.assertTrue(square.wallet_proven("sq:m", "https://r.example:8443/pay", self.A, get))
        self.assertEqual(seen[0], "https://r.example:8443" + square.WELL_KNOWN)
        seen.clear()
        square.wallet_proven("sq:m", "https://[2001:db8::1]:8443/pay", self.A, get)
        self.assertEqual(seen[0], "https://[2001:db8::1]:8443" + square.WELL_KNOWN)

    def test_pinned_get_refuses_a_private_host_before_connecting(self):
        with self.assertRaises(ValueError):
            square.pinned_get("https://h.example/x", resolve=lambda h, p, proto=0: [(0, 0, 0, "", ("10.1.2.3", 443))])
        with self.assertRaises(ValueError):
            square.pinned_get("http://h.example/x")

    def test_a_private_address_is_never_asked(self):
        for addr in ("127.0.0.1", "10.0.0.5", "169.254.169.254", "::1", "192.168.1.2"):
            self.assertFalse(square.public_host("https://h.example", lambda h, p, proto=0, a=addr: [(0, 0, 0, "", (a, 443))]), addr)
        self.assertTrue(square.public_host("https://h.example", lambda h, p, proto=0: [(0, 0, 0, "", ("93.184.216.34", 443))]))
        self.assertFalse(square.public_host("https://h.example", lambda h, p, proto=0: [(0, 0, 0, "", ("93.184.216.34", 443)),
                                                                                        (0, 0, 0, "", ("10.0.0.1", 443))]))

    def test_slow_routes_cannot_hold_the_build(self):
        import time
        def slow(r, w):
            time.sleep(5)
            return True
        t0 = time.time()
        got = square.prove_all([("https://a", "w"), ("https://b", "w")], slow, workers=2, deadline=0.3)
        self.assertLess(time.time() - t0, 2)
        self.assertEqual(got, {("https://a", "w"): False, ("https://b", "w"): False})

    def test_a_vouch_counts_only_from_a_proven_wallet(self):
        thread = [c("1", "sq:a", "square: join\nsells: x\nroute: https://a.example\npayto: %s" % W),
                  c("2", "sq:b", "square: join\nsells: y"),
                  {"id": "v1", "vouch": {"by": "sq:b", "for": "sq:a", "note": "n", "at": "t"}},
                  {"id": "v2", "vouch": {"by": "sq:a", "for": "sq:b", "note": "n", "at": "t"}}]
        s = square.compute(thread, prove=lambda a, r, w: True)
        got = {m["author"]: [v["by_member"] for v in m["vouched_by"]] for m in s["members"]}
        self.assertEqual(got, {"sq:a": [], "sq:b": ["sq:a"]})

    def test_names_are_cleaned_of_every_invisible_character(self):
        for ch in ("\u061c", "\ufeff", "\u00ad", "\u2060", "\u2028", "\u180e"):
            self.assertEqual(square.clean("a" + ch + "b", 40), "a b", repr(ch))


class ReviewTwo(unittest.TestCase):
    """The [review] session's findings, 2026-10-13."""

    def test_one_wallet_backs_one_member(self):
        thread = [c("1", "sq:a", "square: join\nsells: x\nroute: https://a.example\npayto: %s" % W),
                  c("2", "sq:b", "square: join\nsells: y\nroute: https://b.example\npayto: %s" % W)]
        problems = []
        s = square.compute(thread, prove=lambda a, r, w: True, problems=problems)
        self.assertEqual([m["wallet_proven"] for m in s["members"]], [False, False])
        self.assertIn("more than one member", problems[0])

    def test_claims_on_one_wallet_are_checked_together_past_the_cap(self):
        real = square.MAX_PROOFS
        square.MAX_PROOFS = 2
        try:
            other = "0x" + "3" * 40
            thread = [c("1", "sq:a", "square: join\nsells: x\nroute: https://a.example\npayto: %s" % W),
                      c("2", "sq:z", "square: join\nsells: y\nroute: https://z.example\npayto: %s" % W),
                      c("3", "sq:m", "square: join\nsells: z\nroute: https://m.example\npayto: %s" % other)]
            asked = []

            def prove(a, r, w):
                asked.append(a)
                return True
            s = square.compute(thread, prove=prove)
            if "sq:a" in asked or "sq:z" in asked:
                self.assertIn("sq:a", asked)
                self.assertIn("sq:z", asked)                                   # never one without the other
            self.assertFalse(any(m["wallet_proven"] for m in s["members"] if m["author"] in ("sq:a", "sq:z")))
        finally:
            square.MAX_PROOFS = real

    def test_moltbook_and_github_members_are_shown_by_their_handle(self):
        members, _, _ = square.collect([c("1", "mb:someone", "square: join\nname: ausrine\nsells: x"),
                                        c("2", "gh:dev", "square: join\nname: Coinbase\nsells: y"),
                                        c("3", "sq:own", "square: join\nname: own-name\nsells: z")])
        self.assertEqual({k: v["name"] for k, v in members.items()},
                         {"mb:someone": "mb:someone", "gh:dev": "gh:dev", "sq:own": "own-name"})

    def test_blank_looking_characters_are_spaces(self):
        for ch in ("\u3164", "\u2800", "\u00a0", "\u3000", "\u115f"):
            self.assertEqual(square.clean("a" + ch + "b", 40), "a b", repr(ch))
        self.assertEqual(square.clean("\u0301\u0301x", 40), "x")                 # orphan combining marks

    def test_none_means_no_value(self):
        members, _, refused = square.collect([c("1", "mb:g", "square: join\nsells: grades\nroute: none\nprice: none\npayto: none")])
        self.assertEqual(refused, [])
        self.assertEqual((members["mb:g"]["route"], members["mb:g"]["price"], members["mb:g"]["payto"]), (None, None, None))


class ProvePage(unittest.TestCase):
    def test_the_page_signs_exactly_the_text_the_build_checks(self):
        import re as _re
        page = square.prove_page("https://atlas.example", "2026-10-13")
        before = json.loads(_re.search(r"var BEFORE=(\"[^\"]*\")", page).group(1))
        mid = json.loads(_re.search(r",MID=(\"[^\"]*\")", page).group(1))
        self.assertEqual(before + "sq:m" + mid + PROOF["address"], square.proof_message("sq:m", PROOF["address"]))
        self.assertNotIn("innerHTML", page)
        self.assertEqual(page.count("<script>"), 1)
        self.assertIn("personal_sign", page)
        self.assertNotIn("eth_sendTransaction", page)                      # it can only ask for a signature

    def test_the_page_asks_for_the_id_first_and_checks_the_card_wallet(self):
        page = square.prove_page("https://atlas.example", "2026-10-14")
        self.assertLess(page.index('id="prove-member"'), page.index('id="prove-connect"'))   # the id comes first
        self.assertIn("fetch('../square.json'", page)                         # the card's own wallet is looked up
        self.assertIn("That is the wrong wallet", page)                        # and a different one is named plainly
        self.assertIn("accountsChanged", page)                                 # switching accounts is noticed
        self.assertIn("if(!loaded){say(", page)                                # no Sign before the card is checked
        self.assertIn("/functions/v1/square-prove", page)                       # the signature is saved through the checked door
        self.assertEqual(page.count('<nav class="main"'), 1)
        self.assertNotIn('href="https://atlas.example/s/"', page.split("</nav>")[0])   # no site menu on this page
        self.assertIn("Back to the Square", page)
        self.assertNotIn('class="hsearch"', page)

    def test_every_build_writes_it_and_no_member_takes_its_address(self):
        out = tempfile.mkdtemp()
        try:
            s = square.build(out, comments=[c("1", "prove", "square: join\nsells: x")])
            self.assertTrue(os.path.exists(os.path.join(out, "square", "prove", "index.html")))
            self.assertEqual(s["members"][0]["slug"], "member-prove")
        finally:
            shutil.rmtree(out)


class Fomo(unittest.TestCase):
    def test_now_counts_arrivals_founding_places_and_waiting_asks(self):
        now = datetime.datetime(2026, 10, 14, 12, 0)
        thread = [c("1", "sq:a", "square: join\nsells: weather data feed\nroute: https://a.example\npayto: %s" % W,
                    at="2026-10-14T09:00:00"),
                  c("2", "sq:b", "square: join\nsells: audits", at="2026-10-10T09:00:00"),
                  c("3", "sq:b", "square: ask\ntext: need weather data for 30 cities", at="2026-10-14T02:00:00"),
                  c("4", "sq:a", "square: ask\ntext: answered ask", at="2026-10-14T03:00:00"),
                  dict(c("5", "sq:b", "square: offer\ntext: here", at="2026-10-14T04:00:00"), reply_to="4")]
        s = square.compute(thread, prove=lambda a, r, w: a == "sq:a", now=now)
        nw = s["now"]
        self.assertEqual((nw["members"], nw["proven"], nw["joined_today"], nw["joined_this_week"]), (2, 1, 1, 2))
        self.assertEqual((nw["founding"]["taken"], nw["founding"]["left"]), (1, square.FOUNDING - 1))
        self.assertEqual([(a["id"], a["waiting_hours"]) for a in nw["open_asks"]], [("3", 10)])   # the answered one is gone
        cards = {m["author"]: m for m in s["members"]}
        self.assertTrue(cards["sq:a"]["founding"])
        self.assertFalse(cards["sq:b"]["founding"])
        self.assertEqual(cards["sq:a"]["open_asks_in_category"], 1)          # an ask in its own category waits

    def test_the_page_and_the_heartbeat_say_it(self):
        out = tempfile.mkdtemp()
        try:
            square.build(out, comments=[c("1", "sq:b", "square: join\nsells: x"),
                                        c("2", "sq:b", "square: ask\ntext: need <b>data</b>")])
            with open(os.path.join(out, "square", "index.html")) as f:
                page = f.read()
            self.assertIn("Now on the Square:", page)
            self.assertIn("Asks waiting for a seller", page)
            self.assertIn("need &lt;b&gt;data&lt;/b&gt;", page)
            with open(os.path.join(out, "square", "heartbeat.md")) as f:
                hb = f.read()
            self.assertIn("now.open_asks", hb)
            self.assertIn("square_post", hb)
        finally:
            shutil.rmtree(out)


class FoundingAndAsks(unittest.TestCase):
    def test_a_founding_place_is_kept_when_the_proof_lapses(self):
        thread = [c("1", "sq:a", "square: join\nsells: x", at="2026-10-01T00:00:00"),
                  c("2", "sq:b", "square: join\nsells: y\nroute: https://b.example\npayto: %s" % W, at="2026-10-02T00:00:00")]
        s = square.compute(thread, prove=lambda a, r, w: True, founders=["sq:a", "sq:gone"])
        nw = s["now"]["founding"]
        self.assertEqual(nw["members"], ["sq:a", "sq:b"])                # sq:a kept unproven; a departed name drops
        self.assertEqual({m["author"]: m["founding"] for m in s["members"]}, {"sq:a": True, "sq:b": True})

    def test_the_published_list_is_read_and_a_failure_stops_the_build(self):
        import urllib.error as ue
        ok = lambda url: json.dumps({"kind": square.KIND, "now": {"founding": {"members": ["sq:a", 7]}},
                                     "members": [{"author": "sq:p", "wallet_proven": True}, {"author": "sq:q", "wallet_proven": False}]}).encode()
        self.assertEqual(square.published_founders("https://x.example", ok), ["sq:a"])
        self.assertEqual(square.published_state("https://x.example", ok)["proven"], ["sq:p"])

        def missing(url):
            raise ue.HTTPError(url, 404, "no", {}, None)

        def down(url):
            raise OSError("down")
        self.assertEqual(square.published_founders("https://x.example", missing), [])
        self.assertIsNone(square.published_founders("https://x.example", down))

    def test_the_site_is_read_first_then_the_data_branch_and_a_failure_is_never_no_square(self):
        import urllib.error as ue
        site_json = json.dumps({"kind": square.KIND, "now": {"founding": {"members": ["sq:site"]}}, "members": []}).encode()
        data_json = json.dumps({"kind": square.KIND, "now": {"founding": {"members": ["sq:data"]}}, "members": []}).encode()

        def get(site_answer, data_answer):
            def g(url):
                a = data_answer if "raw.githubusercontent" in url else site_answer
                if isinstance(a, Exception):
                    raise a
                return a
            return g
        nf = ue.HTTPError("u", 404, "no", {}, None)
        blocked = ue.HTTPError("u", 403, "no", {}, None)
        self.assertEqual(square.published_square("https://x.example", get(site_json, data_json))["now"]["founding"]["members"], ["sq:site"])
        self.assertEqual(square.published_square("https://x.example", get(nf, data_json))["now"]["founding"]["members"], ["sq:data"])
        self.assertEqual(square.published_square("https://x.example", get(blocked, data_json))["now"]["founding"]["members"], ["sq:data"])
        self.assertEqual(square.published_square("https://x.example", get(nf, nf)), {})
        self.assertIsNone(square.published_square("https://x.example", get(blocked, nf)))
        self.assertIsNone(square.published_square("https://x.example", get(nf, OSError("down"))))
        self.assertEqual(square.published_square("https://x.example", get(b"<html>not json", nf)), None)   # a broken answer is a failure
        self.assertEqual(square.published_square("https://x.example", get(b'{"kind": "other"}', nf)), {})  # something else there: no Square

    def test_the_published_square_is_read_where_it_is_served_without_a_redirect(self):
        seen = []
        square.published_square(get=lambda url: seen.append(url) or json.dumps({"kind": square.KIND}).encode())
        self.assertEqual(seen, [square.PUBLIC_SITE + "/square/square.json"])
        self.assertNotIn("github.io", square.PUBLIC_SITE)

    def test_a_restored_square_is_written_as_it_was_and_says_so(self):
        out = tempfile.mkdtemp()
        try:
            s = square.build(out, comments=[c("1", "penny-agent", JOIN)], founders=[], site="https://atlas.example")
            with open(os.path.join(out, "square", "square.json")) as f:
                saved = json.load(f)
            shutil.rmtree(os.path.join(out, "square"))
            self.assertTrue(square.restore(out, saved, "https://atlas.example", why="the thread was down"))
            with open(os.path.join(out, "square", "index.html")) as f:
                page = f.read()
            self.assertIn("the thread was down; this is the Square as published", page)
            self.assertTrue(os.path.exists(os.path.join(out, "square", "penny-agent", "index.html")))
            with open(os.path.join(out, "square", "square.json")) as f:
                again = json.load(f)
            self.assertEqual(again["members"], saved["members"])
            self.assertIn("the thread was down", again["problems"][-1])
            self.assertFalse(square.restore(out, {"kind": "x"}, "https://atlas.example"))
            self.assertFalse(square.restore(out, "junk", "https://atlas.example"))
        finally:
            shutil.rmtree(out)

    def test_an_old_waiting_ask_counts_past_the_feed_cap(self):
        real = square.FEED
        square.FEED = 2
        try:
            thread = [c("1", "sq:b", "square: join\nsells: y")]
            thread += [c(str(10 + i), "sq:b", "square: post\ntext: chatter %d" % i, at="2026-10-14T0%d:00:00" % i) for i in range(5)]
            thread.append(c("9", "sq:b", "square: ask\ntext: old ask", at="2026-10-01T00:00:00"))
            s = square.compute(thread, now=datetime.datetime(2026, 10, 14, 12, 0))
            self.assertEqual(len(s["feed"]), 2)                               # the display is capped
            self.assertEqual([a["id"] for a in s["now"]["open_asks"]], ["9"])  # the waiting count is not
        finally:
            square.FEED = real

    def test_an_ask_past_the_window_stops_waiting_whatever_door_it_came_through(self):
        thread = [c("1", "mb:b", "square: join\nsells: y"),
                  c("2", "mb:b", "square: ask\ntext: ancient ask", at="2026-08-01T00:00:00"),
                  c("3", "gh:z", "square: ask\ntext: fresh ask", at="2026-10-13T00:00:00")]
        s = square.compute(thread, now=datetime.datetime(2026, 10, 14, 12, 0))
        self.assertEqual([a["id"] for a in s["now"]["open_asks"]], ["3"])

    def test_a_nested_moltbook_reply_or_an_issue_comment_answers_an_ask(self):
        ask = c("2", "mb:b", "square: ask\ntext: who sells weather?", at="2026-10-13T00:00:00")
        ask["replies"] = [c("3", "mb:b", "bump", at="2026-10-13T01:00:00")]   # the asker's own bump is no answer
        lone = c("4", "mb:b", "square: ask\ntext: still waiting", at="2026-10-13T00:00:00")
        answered = c("5", "mb:b", "square: ask\ntext: answered in plain words", at="2026-10-13T00:00:00")
        answered["replies"] = [c("6", "mb:z", "try weatherbot", at="2026-10-13T02:00:00")]
        issue = c("gh-7", "gh:q", "square: ask\ntext: on GitHub", at="2026-10-13T00:00:00")
        issue["replied"] = True
        s = square.compute([c("1", "mb:b", "square: join\nsells: y"), ask, lone, answered, issue],
                           now=datetime.datetime(2026, 10, 14, 12, 0))
        self.assertEqual(sorted(a["id"] for a in s["now"]["open_asks"]), ["2", "4"])
        recent = (datetime.datetime.utcnow() - datetime.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

        def gh(logins):
            def get(url):
                if "/comments" in url:
                    return [{"user": {"login": x}} for x in logins]
                return [{"number": 7, "user": {"login": "q"}, "title": "square: ask", "body": "text: help?", "created_at": recent, "comments": 2}]
            return get
        self.assertTrue(square.fetch_issues(get=gh(["q", "helper"]))[0]["replied"])
        self.assertFalse(square.fetch_issues(get=gh(["q"]))[0]["replied"])        # the asker's own bump
        problems = []

        def broken(url):
            if "/comments" in url:
                raise OSError("rate limited")
            return gh([])(url)
        got = square.fetch_issues(get=broken, problems=problems)
        self.assertFalse(got[0]["replied"])                                      # unread answers leave it waiting
        self.assertNotIn("_comments", got[0])
        self.assertTrue(problems)

    def test_a_square_ask_answered_only_by_someone_else_and_asks_posted_as_replies_count(self):
        t = "2026-10-13T0%d:00:00"
        posts = [c("1", "sq:b", "square: join\nsells: y"),
                 c("sq-post-1", "sq:b", "square: ask\ntext: first", at=t % 1),
                 c("sq-post-2", "sq:b", "square: post\ntext: more detail", at=t % 2),
                 c("sq-post-3", "sq:z", "square: ask\ntext: me too, any?", at=t % 3)]
        posts[2]["reply_to"] = "sq-post-1"
        posts[3]["reply_to"] = "sq-post-1"
        s = square.compute(posts, now=datetime.datetime(2026, 10, 14, 12, 0))
        # sq:z's reply answers sq-post-1 (someone else replied); sq:b's own detail would not have;
        # sq:z's ask, posted as a reply, still waits
        self.assertEqual([a["id"] for a in s["now"]["open_asks"]], ["sq-post-3"])
        s = square.compute(posts[:3], now=datetime.datetime(2026, 10, 14, 12, 0))
        self.assertEqual([a["id"] for a in s["now"]["open_asks"]], ["sq-post-1"])

    def test_a_long_thread_shows_its_newest_replies_and_comment_pages_are_followed(self):
        posts = [c("1", "sq:b", "square: join\nsells: y"), c("p", "sq:b", "square: post\ntext: root", at="2026-10-13T00:00:00")]
        for i in range(square.MAX_REPLIES + 5):
            r = c("r%02d" % i, "sq:b", "square: post\ntext: reply %d" % i, at="2026-10-13T01:%02d:00" % i)
            r["reply_to"] = "p"
            posts.append(r)
        s = square.compute(posts, now=datetime.datetime(2026, 10, 14, 12, 0))
        root = [f for f in s["feed"] if f["id"] == "p"][0]
        self.assertEqual((len(root["replies"]), root["more_replies"]), (square.MAX_REPLIES, 5))
        self.assertEqual(root["replies"][-1]["id"], "r%02d" % (square.MAX_REPLIES + 4))
        recent = (datetime.datetime.utcnow() - datetime.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

        def get(url):
            if "/comments" in url:
                return [{"user": {"login": "q"}}] * 100 if url.endswith("&page=1") else [{"user": {"login": "helper"}}]
            return [{"number": 7, "user": {"login": "q"}, "title": "square: ask", "body": "text: help?", "created_at": recent, "comments": 101}]
        self.assertTrue(square.fetch_issues(get=get)[0]["replied"])            # the answer on page 2 is found

    def test_a_recent_reply_brings_an_old_thread_into_the_capped_feed(self):
        real = square.FEED
        square.FEED = 2
        try:
            posts = [c("1", "sq:b", "square: join\nsells: y"),
                     c("old", "sq:b", "square: post\ntext: old root", at="2026-10-01T00:00:00")]
            posts += [c("n%d" % i, "sq:b", "square: post\ntext: news %d" % i, at="2026-10-10T0%d:00:00" % i) for i in range(3)]
            r = c("late", "sq:b", "square: post\ntext: fresh reply", at="2026-10-13T00:00:00")
            r["reply_to"] = "old"
            posts.append(r)
            s = square.compute(posts, now=datetime.datetime(2026, 10, 14, 12, 0))
            self.assertEqual([f["id"] for f in s["feed"]], ["old", "n2"])
        finally:
            square.FEED = real

    def test_comment_reads_are_spent_on_asks_only(self):
        recent = (datetime.datetime.utcnow() - datetime.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        issues = [{"number": i, "user": {"login": "q"}, "title": "square: join", "body": "sells: x", "created_at": recent,
                   "comments": 3} for i in range(1, square.MAX_ISSUE_COMMENT_READS + 5)]
        issues += [{"number": 500 + i, "user": {"login": "q"}, "title": "square: ask", "body": "", "created_at": recent,
                    "comments": 3} for i in range(square.MAX_ISSUE_COMMENT_READS + 5)]   # asks with no text: not shown, not read
        issues.append({"number": 999, "user": {"login": "q"}, "title": "square: ask", "body": "text: anyone?",
                       "created_at": recent, "comments": 1})
        read = []

        def get(url):
            if "/comments" in url:
                read.append(url)
                return [{"user": {"login": "helper"}}]
            return issues
        got = square.fetch_issues(get=get)
        self.assertEqual(len(read), 1)
        self.assertTrue([g for g in got if g["id"] == "gh-999"][0]["replied"])

    def test_an_answer_under_the_askers_own_follow_up_answers_the_ask(self):
        t = "2026-10-13T0%d:00:00"
        posts = [c("1", "sq:b", "square: join\nsells: y"),
                 c("a", "sq:b", "square: ask\ntext: who sells maps?", at=t % 1),
                 c("f", "sq:b", "square: post\ntext: on Base please", at=t % 2),
                 c("h", "sq:z", "square: post\ntext: mapbot does", at=t % 3)]
        posts[2]["reply_to"], posts[3]["reply_to"] = "a", "f"
        s = square.compute(posts, now=datetime.datetime(2026, 10, 14, 12, 0))
        self.assertEqual(s["now"]["open_asks"], [])
        ask = c("m", "mb:b", "square: ask\ntext: who sells maps?", at=t % 1)
        follow = c("mf", "mb:b", "on Base please", at=t % 2)
        follow["replies"] = [c("mh", "mb:z", "mapbot does", at=t % 3)]
        ask["replies"] = [follow]
        s = square.compute([c("2", "mb:b", "square: join\nsells: y"), ask], now=datetime.datetime(2026, 10, 14, 12, 0))
        self.assertEqual(s["now"]["open_asks"], [])

    def test_a_saved_input_build_carries_the_published_founders(self):
        d = tempfile.mkdtemp()
        seen = {}
        real_pf, real_build = square.published_state, square.build
        try:
            with open(os.path.join(d, "in.json"), "w") as f:
                json.dump([c("1", "sq:a", "square: join\nsells: x")], f)
            square.published_state = lambda *a, **k: {"founders": ["sq:a"], "proven": ["sq:p"]}
            square.build = lambda *a, **k: seen.update(k) or None
            square.main(["--flows-dir", d, "--out", d, "--from-file", os.path.join(d, "in.json")])
            self.assertEqual((seen["founders"], seen["proven_before"]), (["sq:a"], ["sq:p"]))
            square.published_state = lambda *a, **k: None
            seen.clear()
            self.assertEqual(square.main(["--flows-dir", d, "--out", d, "--from-file", os.path.join(d, "in.json")]), 1)
            self.assertEqual(seen, {})                                       # unreadable founders: no build at all
        finally:
            square.published_state, square.build = real_pf, real_build
            shutil.rmtree(d)

    def test_the_ask_rule_is_on_the_join_page_and_the_heartbeat(self):
        self.assertIn("would pay a stranger for", square.join_md("https://atlas.example"))
        self.assertIn("would pay a stranger for", square.heartbeat_md("https://atlas.example"))


class PageBudget(unittest.TestCase):
    def test_only_proven_active_or_new_members_get_a_page(self):
        real = square.NEW_MEMBER_DAYS
        square.NEW_MEMBER_DAYS = 30
        out = tempfile.mkdtemp()
        try:
            s = square.build(out, comments=[c("1", "old", "square: join\nsells: x", at="2020-01-01T00:00:00"),
                                            c("2", "talker", "square: join\nsells: y", at="2020-01-01T00:00:00"),
                                            c("3", "talker", "square: ask\ntext: anyone?", at="2020-01-02T00:00:00")])
            pages = {m["author"]: m["has_page"] for m in s["members"]}
            self.assertEqual(pages, {"old": False, "talker": True})
            self.assertFalse(os.path.exists(os.path.join(out, "square", "old")))
            self.assertTrue(os.path.exists(os.path.join(out, "square", "talker", "index.html")))
            self.assertTrue(square.new_member("2026-10-01", datetime.date(2026, 10, 13)))
            self.assertFalse(square.new_member("2026-08-01", datetime.date(2026, 10, 13)))
            self.assertFalse(square.new_member("garbage"))
        finally:
            square.NEW_MEMBER_DAYS = real
            shutil.rmtree(out)


class FrontPage(unittest.TestCase):
    """The human page, 2026-10-14: a clear front, the numbers, a picture, an activity feed, member cards."""

    def test_the_front_the_picture_and_the_feed(self):
        out = tempfile.mkdtemp()
        try:
            thread = [c("1", "sq:a<b>", "square: join\nsells: maps <i>x</i>\nroute: https://a.example/r\npayto: %s" % W,
                        at="2026-10-13T09:00:00"),
                      c("2", "mb:bee", "square: join\nsells: checks", at="2026-10-13T10:00:00"),
                      c("3", "mb:bee", "square: ask\ntext: need a <script>map</script>", at="2026-10-13T11:00:00"),
                      {"id": "v1", "vouch": {"by": "sq:a<b>", "for": "mb:bee", "note": "good", "at": "2026-10-13T12:00:00"}}]
            square.build(out, comments=thread, founders=[], prove=lambda a, r, w: True, site="https://atlas.example")
            with open(os.path.join(out, "square", "index.html")) as f:
                page = f.read()
            for want in ("Send your agent to join", "Prove your wallet", "Founding places left", 'class="sq-graph"',
                         "is looking for", "vouched for bee", 'class="mtile"', '<span class="src">Moltbook</span>'):
                self.assertIn(want, page)
            self.assertNotIn("<b>", page.split('<svg class="sq-graph"')[1].split("</svg>")[0])   # names never become markup
            self.assertNotIn("<script>map", page)
            self.assertNotIn("<i>x</i>", page)
            self.assertNotIn("innerHTML", page)
            self.assertEqual(page.count("<script>"), 1)
            self.assertIn('<details class="navmore"><summary>Explore</summary>', page)
            svg = page.split('<svg class="sq-graph"')[1].split("</svg>")[0]
            self.assertIn('class="lv"', svg)                                      # the vouch is drawn between members
            self.assertIn('data-built="', page)                                   # live posts only after the build
        finally:
            shutil.rmtree(out)


class Pages(unittest.TestCase):
    def test_build_writes_the_square_escaped_with_safe_links(self):
        out = tempfile.mkdtemp()
        try:
            thread = [c("1", "penny-agent", JOIN),
                      c("2", "x<script>", "square: join\nsells: <b>bold</b> \"quoted\"\nroute: https://h.example/a?b=1&c=2")]
            s = square.build(out, comments=thread, site="https://atlas.example", as_of="2026-10-13")
            self.assertEqual(len(s["members"]), 2)
            with open(os.path.join(out, "square", "index.html")) as f:
                page = f.read()
            self.assertNotIn("x<script>", page)                          # a member's name never becomes markup
            self.assertEqual(page.count("<script>"), 1)                 # the only script is the Square's live feed
            self.assertIn("a.rel='nofollow ugc noopener'", page)         # a live route is a plain https link, nofollow
            self.assertNotIn("innerHTML", page)
            self.assertNotIn("<b>bold</b>", page)
            self.assertIn('rel="nofollow ugc noopener"', page)
            self.assertIn("No chain numbers yet", page)                 # no flows window given
            o2 = os.path.join(out, "sol")
            sol = square.build(o2, comments=[c("9", "s", "square: join\nsells: x\npayto: 9SVcuCZxaQLMiLBziPrrr6L3KRAxLhRis56Zq4ovcRVy")])
            with open(os.path.join(o2, "square", "index.html")) as f:
                self.assertIn("not Solana", f.read())
            self.assertEqual(sol["members"][0]["chain"], "Solana")
            with open(os.path.join(out, "square", "square.json")) as f:
                j = json.load(f)
            self.assertEqual(j["kind"], square.KIND)
            self.assertTrue(os.path.exists(os.path.join(out, "square", "penny-agent", "index.html")))
            with open(os.path.join(out, "square", "join.md")) as f:
                self.assertIn("square: join", f.read())
            for root, _, files in os.walk(out):                       # the stem the Atlas never writes
                for name in files:
                    with open(os.path.join(root, name)) as f:
                        self.assertNotIn("verif", f.read().lower())
        finally:
            shutil.rmtree(out)

    def test_two_names_that_slug_alike_get_two_pages(self):
        out = tempfile.mkdtemp()
        try:
            s = square.build(out, comments=[c("1", "a.b", "square: join\nsells: x"), c("2", "a b", "square: join\nsells: y")])
            slugs = sorted(m["slug"] for m in s["members"])
            self.assertEqual(len(set(slugs)), 2)
        finally:
            shutil.rmtree(out)

    def test_names_alike_after_the_first_bytes_still_get_two_pages(self):
        out = tempfile.mkdtemp()
        try:
            s = square.build(out, comments=[c("1", "abcdef!", "square: join\nsells: x"),
                                            c("2", "abcdef@", "square: join\nsells: y")])
            self.assertEqual(len({m["slug"] for m in s["members"]}), 2)
        finally:
            shutil.rmtree(out)

    def test_a_hashed_slug_never_lands_on_another_members_slug(self):
        import hashlib
        h = hashlib.sha256("a.b".encode()).hexdigest()[:12]
        out = tempfile.mkdtemp()
        try:
            s = square.build(out, comments=[c("1", "a.b", "square: join\nsells: x"), c("2", "a b", "square: join\nsells: y"),
                                            c("3", "a-b-" + h, "square: join\nsells: z")])
            self.assertEqual(len({m["slug"] for m in s["members"]}), 3)
        finally:
            shutil.rmtree(out)

    def test_a_member_who_leaves_loses_the_page(self):
        out = tempfile.mkdtemp()
        try:
            square.build(out, comments=[c("1", "m", "square: join\nsells: x"), c("2", "gone", "square: join\nsells: y")])
            os.makedirs(os.path.join(out, "square", "notes"))          # a folder that is not a member page stays
            square.build(out, comments=[c("1", "m", "square: join\nsells: x")])
            self.assertTrue(os.path.exists(os.path.join(out, "square", "m", "index.html")))
            self.assertFalse(os.path.exists(os.path.join(out, "square", "gone")))
            self.assertTrue(os.path.isdir(os.path.join(out, "square", "notes")))
        finally:
            shutil.rmtree(out)

    def test_a_chosen_thread_is_the_one_the_pages_point_to(self):
        out = tempfile.mkdtemp()
        try:
            s = square.build(out, founders=[], prove=lambda a, r, w: False, threads=["other-thread"], get=lambda url: {"comments": []}, issues=None, own=False)
            self.assertEqual(s["threads"], ["other-thread"])
            with open(os.path.join(out, "square", "join.md")) as f:
                self.assertIn("/post/other-thread", f.read())
            with open(os.path.join(out, "square", "index.html")) as f:
                self.assertIn("/post/other-thread", f.read())
        finally:
            shutil.rmtree(out)

    def test_no_thread_readable_writes_nothing(self):
        out = tempfile.mkdtemp()
        try:
            def get(url):
                raise OSError("down")
            self.assertIsNone(square.build(out, founders=[], prove=lambda a, r, w: False, get=get))
            self.assertFalse(os.path.exists(os.path.join(out, "square")))
        finally:
            shutil.rmtree(out)

    def test_numbers_come_from_the_board_row_of_the_payto_wallet(self):
        row = {"wallet": W, "customers": 9, "returning": 4, "independent": 3, "fake_cost_usd": 0.14, "top_payer_share_pct": 20.0, "one_payer_most": False,
               "daily_usdc": [1, 2, 3, 4, 5, 6, 7], "shape": "ramping", "usdc": 28.0, "rank": 3, "reason": "r"}
        real = square.board.compute
        square.board.compute = lambda folder, snap: {"sellers": [row], "window": {"from": "a", "to": "b"}}
        out = tempfile.mkdtemp()
        try:
            s = square.build(out, flows_dir="flows", prove=lambda a, r, w: r == "https://m.example/r",
                             comments=[c("1", "m", "square: join\nsells: x\nroute: https://m.example/r\npayto: %s" % W.upper().replace("0X", "0x")),
                                       c("2", "n", "square: join\nsells: y"),
                                       c("3", "copycat", "square: join\nsells: z\nroute: https://copy.example/r\npayto: %s" % W)])
        finally:
            square.board.compute = real
            shutil.rmtree(out)
        self.assertEqual([m["author"] for m in s["members"]][0], "m")            # members with numbers first
        self.assertIsNone(next(x for x in s["members"] if x["author"] == "copycat")["numbers"])   # an unproven claim borrows nothing
        self.assertEqual((s["members"][0]["numbers"]["customers"], s["members"][0]["numbers"]["returning"]), (9, 4))
        self.assertIsNone(next(x for x in s["members"] if x["author"] == "n")["numbers"])


class SecurityRound(unittest.TestCase):
    """The [review] session's recheck of #212, 2026-10-13: starvation, slow drip, marks, lapsing."""

    def test_three_hundred_claims_on_a_wallet_cannot_starve_its_owner(self):
        thread = [c("v", "sq:victim", "square: join\nsells: real\nroute: https://v.example\npayto: %s" % W, at="2026-10-01T00:00:00")]
        thread += [c("a%03d" % i, "sq:att%03d" % i, "square: join\nsells: fake\nroute: https://v.example\npayto: %s" % W,
                     at="2026-09-01T00:00:00") for i in range(301)]                 # older than the victim, all unsigned
        asked, problems = [], []

        def prove(a, r, w):
            asked.append(a)
            return a == "sq:victim"
        s = square.compute(thread, prove=prove, problems=problems, proven_before=["sq:victim"])
        self.assertIn("sq:victim", asked)
        self.assertLessEqual(len(asked), square.MAX_CLAIMS)
        self.assertTrue([m for m in s["members"] if m["author"] == "sq:victim"][0]["wallet_proven"])
        self.assertTrue(any("more than %d claims" % square.MAX_CLAIMS in p for p in problems))
        asked.clear()
        s = square.compute(thread, prove=prove, problems=[], proven_before=[])  # never proven before: the oldest claims go first
        self.assertEqual(len(asked), square.MAX_CLAIMS)
        self.assertNotIn("sq:victim", asked)                                  # that is the known residue: a wallet claimed
        self.assertTrue(s["now"]["problems"])                                   # by 300 strangers first is reported, not silent

    def test_a_wallet_group_left_out_is_reported_and_proven_members_go_first(self):
        real = square.MAX_PROOFS
        square.MAX_PROOFS = 1
        try:
            other = "0x" + "3" * 40
            thread = [c("1", "sq:a", "square: join\nsells: x\nroute: https://a.example\npayto: %s" % W),
                      c("2", "sq:b", "square: join\nsells: y\nroute: https://b.example\npayto: %s" % other)]
            asked, problems = [], []
            square.compute(thread, prove=lambda a, r, w: asked.append(a) or True, problems=problems, proven_before=["sq:b"])
            self.assertEqual(asked, ["sq:b"])
            self.assertTrue(any("not checked this build" in p for p in problems))
        finally:
            square.MAX_PROOFS = real

    def test_one_url_is_fetched_once_for_many_claims(self):
        calls = []

        def fetch(url):
            calls.append(url)
            if url.endswith(square.WELL_KNOWN):
                return 200, {}, b"sig sq:m 0x" + b"0" * 130
            raise OSError("down")
        get = square._memo(fetch)
        for _ in range(5):
            self.assertEqual(get("https://h.example" + square.WELL_KNOWN)[0], 200)
            with self.assertRaises(OSError):
                get("https://h.example/x")
        self.assertEqual(len(calls), 2)
        import threading
        import time
        slow_calls = []

        def slow(url):
            slow_calls.append(url)
            time.sleep(0.2)
            return 200, {}, b""
        g = square._memo(slow)
        ts = [threading.Thread(target=lambda: g("https://one.example/x")) for _ in range(8)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(len(slow_calls), 1)                              # eight claims in flight at once: one request

    def test_overlay_and_enclosing_marks_are_dropped_everywhere(self):
        self.assertEqual(square.clean("V\u0336ilija", 40), "Vilija")                # strike-through
        self.assertEqual(square.clean("a\u20dd", 40), "a")                           # enclosing circle
        self.assertEqual(square.clean("e\u0301", 40), "\u00e9")                     # an accent stays
        self.assertEqual(square.clean("e\u0301\u0302\u0303\u0304", 40), "\u00e9\u0302")   # at most two marks a letter

    def test_api_members_about_to_lapse_are_named(self):
        j = c("1", "sq:quiet", "square: join\nsells: x", at="2026-09-01T00:00:00")
        j["active_at"] = "2026-09-20T00:00:00"
        k = c("2", "sq:busy", "square: join\nsells: y", at="2026-09-01T00:00:00")
        k["active_at"] = "2026-10-13T00:00:00"             # updated_at moves on every post, server-side
        s = square.compute([j, k, c("3", "sq:busy", "square: post\ntext: hi", at="2026-10-13T00:00:00"),
                            c("4", "mb:m", "square: join\nsells: z", at="2026-01-01T00:00:00")],
                           now=datetime.datetime(2026, 10, 14, 12, 0))
        self.assertEqual(s["now"]["lapsing"]["members"], [{"member": "sq:quiet", "days_left": 6}])

    def test_a_server_dripping_headers_is_cut_at_the_deadline(self):
        import shutil as sh
        import ssl
        import subprocess
        import threading
        import time
        if not sh.which("openssl"):
            self.skipTest("no openssl")
        d = tempfile.mkdtemp()
        try:
            crt, key = os.path.join(d, "c.pem"), os.path.join(d, "k.pem")
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", crt,
                            "-days", "1", "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost"],
                           check=True, capture_output=True)
            srv = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            srv.load_cert_chain(crt, key)
            ls = socket.socket()
            ls.bind(("127.0.0.1", 0))
            ls.listen(1)
            port = ls.getsockname()[1]
            stop = threading.Event()

            def serve():
                try:
                    conn, _ = ls.accept()
                    with srv.wrap_socket(conn, server_side=True) as t:
                        t.recv(4096)
                        t.sendall(b"HTTP/1.1 200 OK\r\n")
                        while not stop.is_set():                              # one header line every 0.3 s, forever
                            t.sendall(b"X-Drip: a\r\n")
                            time.sleep(0.3)
                except OSError:
                    pass
            threading.Thread(target=serve, daemon=True).start()
            cli = ssl.create_default_context(cafile=crt)
            real = square.vetted_addresses
            square.vetted_addresses = lambda host, resolve=None: ["127.0.0.1"]
            t0 = time.monotonic()
            try:
                with self.assertRaises(Exception):
                    square.pinned_get("https://localhost:%d/x" % port, timeout=1, context=cli)
            finally:
                square.vetted_addresses = real
                stop.set()
                ls.close()
            self.assertLess(time.monotonic() - t0, 3)
        finally:
            shutil.rmtree(d)


class QuickBuild(unittest.TestCase):
    """The quarter-hour build (Atlas square.yml): a wallet the live Square proved, with the same member, route
    and wallet, is not asked again; anything new or changed is."""

    def thread(self, payto_b=None):
        other = "0x" + "3" * 40
        return [c("1", "sq:a", "square: join\nsells: x\nroute: https://a.example/r\npayto: %s" % W),
                c("2", "sq:b", "square: join\nsells: y\nroute: https://b.example/r\npayto: %s" % (payto_b or other))]

    def test_an_unchanged_proven_wallet_is_not_asked_again(self):
        asked = []
        trusted = {"sq:a": ("https://a.example/r", W.lower())}
        s = square.compute(self.thread(), prove=lambda a, r, w: asked.append(a) or True, trusted=trusted)
        self.assertEqual(asked, ["sq:b"])                                       # only the one not proven before
        self.assertEqual({m["author"]: m["wallet_proven"] for m in s["members"]}, {"sq:a": True, "sq:b": True})

    def test_a_changed_route_or_wallet_is_asked_again(self):
        asked = []
        trusted = {"sq:a": ("https://a.example/old", W.lower()), "sq:b": ("https://b.example/r", "0x" + "4" * 40)}
        s = square.compute(self.thread(), prove=lambda a, r, w: asked.append(a) or False, trusted=trusted)
        self.assertEqual(sorted(asked), ["sq:a", "sq:b"])
        self.assertFalse(any(m["wallet_proven"] for m in s["members"]))

    def test_trust_does_not_get_around_one_wallet_one_member(self):
        # sq:b now claims sq:a's wallet and proves it: the wallet backs neither, trusted or not
        trusted = {"sq:a": ("https://a.example/r", W.lower())}
        s = square.compute(self.thread(payto_b=W), prove=lambda a, r, w: True, trusted=trusted, problems=[])
        self.assertFalse(any(m["wallet_proven"] for m in s["members"]))

    def test_the_morning_build_trusts_nothing(self):
        asked = []
        square.compute(self.thread(), prove=lambda a, r, w: asked.append(a) or True)
        self.assertEqual(sorted(asked), ["sq:a", "sq:b"])

    def test_published_state_carries_what_each_proven_card_was_proven_with(self):
        ok = lambda url: json.dumps({"kind": square.KIND, "now": {"founding": {"members": []}}, "members": [
            {"author": "sq:p", "wallet_proven": True, "route": "https://p.example/r", "payto": "0xABC"},
            {"author": "sq:q", "wallet_proven": False, "route": "https://q.example/r", "payto": "0xdef"},
            {"author": "sq:r", "wallet_proven": True, "route": None, "payto": "0x1"}]}).encode()
        self.assertEqual(square.published_state("https://x.example", ok)["trusted"], {"sq:p": ("https://p.example/r", "0xabc")})

    def test_only_a_quick_build_reads_the_trust(self):
        seen = {}

        def fake_compute(*a, **k):
            seen["trusted"] = k.get("trusted")
            return {"members": [], "feed": []}
        real_compute, real_write, real_state = square.compute, square.write_square, square.published_state
        square.compute, square.write_square = fake_compute, lambda *a, **k: None
        square.published_state = lambda *a, **k: {"founders": [], "proven": ["sq:p"], "sigs": {},
                                                   "trusted": {"sq:p": ("https://p.example/r", "0xabc")}}
        try:
            with tempfile.TemporaryDirectory() as d:
                square.build(d, threads=[], issues=None, own=False, prove=lambda a, r, w: True)
                self.assertIsNone(seen["trusted"])
                square.build(d, threads=[], issues=None, own=False, prove=lambda a, r, w: True, quick=True)
                self.assertEqual(seen["trusted"], {"sq:p": ("https://p.example/r", "0xabc")})
        finally:
            square.compute, square.write_square, square.published_state = real_compute, real_write, real_state


def joins(*names, at="2026-10-13T01:00:00"):
    return [c("j-" + n, n, "square: join\nsells: work by %s" % n, at) for n in names]


FOUND = """square: team
team: Pre-pay Check
sells: before you pay an agent business: are its buyers real, does it deliver
price: 8
role: payer independence
members: mb:b, mb:c, mb:d
checker: mb:c
split: mb:a 40, mb:b 30, mb:c 30"""
TX1 = "0x" + "ab" * 32


class Teams(unittest.TestCase):
    def teams(self, posts):
        return square.compute(joins("mb:a", "mb:b", "mb:c", "mb:d", "mb:e") + posts)["teams"]

    def test_a_block_is_read_with_its_fields(self):
        e, why = square.entry("team", square.parse(FOUND)["fields"], "mb:a", "2026-10-13T02:00:00", "t1")
        self.assertIsNone(why)
        self.assertEqual((e["team_slug"], e["price"], e["members"], e["checker"]),
                         ("pre-pay-check", 8.0, ["mb:b", "mb:c", "mb:d"], "mb:c"))
        self.assertEqual(e["split"], [["mb:a", 40.0], ["mb:b", 30.0], ["mb:c", 30.0]])

    def test_bad_team_fields_are_refused_with_a_reason(self):
        for fields, word in (({"sells": "x"}, "team:"), ({"team": "t", "members": "bob"}, "Square ids"),
                             ({"team": "t", "checker": "<b>"}, "checker"), ({"team": "t", "split": "mb:a lots"}, "split"),
                             ({"team": "t", "price": "1e9"}, "between"), ({"team": "t", "route": "http://x.example"}, "https")):
            e, why = square.entry("team", fields, "mb:a", "", "x")
            self.assertIsNone(e)
            self.assertIn(word, why)
        e, why = square.entry("team-job", {"team": "t", "tx": "0x12"}, "mb:a", "", "x")
        self.assertIn("64 hex", why)
        e, why = square.entry("team-job", {"team": "t", "tx": TX1, "verdict": "great"}, "mb:a", "", "x")
        self.assertIn("pass or fail", why)

    def test_nobody_is_on_a_team_without_saying_yes(self):
        t = self.teams([c("t1", "mb:a", FOUND, "2026-10-13T02:00:00"),
                        c("t2", "mb:b", "square: team\nteam: pre-pay check\nrole: evidence", "2026-10-13T03:00:00"),
                        c("t3", "mb:e", "square: team\nteam: Pre-pay Check\nrole: gatecrasher", "2026-10-13T03:00:00")])[0]
        self.assertEqual([m["author"] for m in t["members"]], ["mb:a", "mb:b"])   # e said yes but was never named
        self.assertEqual(t["invited"], ["mb:c", "mb:d"])                          # named, silent: invited only
        self.assertEqual([m["role"] for m in t["members"]], ["payer independence", "evidence"])
        self.assertIsNone(t["checker"])                                            # c has not said yes
        self.assertIsNone(t["split"])                                              # names c, not on the team
        self.assertIn("not on the team", t["split_problem"])
        self.assertTrue(t["shown"])

    def test_the_founder_keeps_the_name_and_only_its_newest_post_defines_it(self):
        t = self.teams([c("t1", "mb:a", FOUND, "2026-10-13T02:00:00"),
                        c("t2", "mb:e", "square: team\nteam: pre-pay check\nsells: hijacked\nmembers: mb:e", "2026-10-13T02:30:00"),
                        c("t3", "mb:a", FOUND.replace("price: 8", "price: 12"), "2026-10-13T04:00:00")])[0]
        self.assertEqual((t["lead"], t["sells"][:10], t["price"]), ("mb:a", "before you", 12.0))

    def test_a_split_and_a_checker_once_everyone_said_yes(self):
        yes = [c("y" + n, n, "square: team\nteam: pre-pay check\nrole: r-" + n, "2026-10-13T03:00:00") for n in ("mb:b", "mb:c")]
        t = self.teams([c("t1", "mb:a", FOUND, "2026-10-13T02:00:00")] + yes)[0]
        self.assertEqual(t["checker"], "mb:c")
        self.assertEqual(t["split"], [["mb:a", 40.0], ["mb:b", 30.0], ["mb:c", 30.0]])
        bad = self.teams([c("t1", "mb:a", FOUND.replace("mb:c 30", "mb:c 20"), "2026-10-13T02:00:00")] + yes)[0]
        self.assertIsNone(bad["split"])
        self.assertIn("100", bad["split_problem"])

    def test_a_verdict_counts_only_from_the_checker(self):
        yes = [c("y" + n, n, "square: team\nteam: pre-pay check", "2026-10-13T03:00:00") for n in ("mb:b", "mb:c")]
        job = "square: team-job\nteam: pre-pay check\ntx: %s\ntext: %s"
        t = self.teams([c("t1", "mb:a", FOUND, "2026-10-13T02:00:00")] + yes + [
            c("j1", "mb:b", job % (TX1, "a 3-page check of api.example\nverdict: pass"), "2026-10-13T05:00:00"),
            c("j2", "mb:e", job % ("0x" + "cd" * 32, "not on the team"), "2026-10-13T05:00:00"),
            c("j3", "mb:c", job % (TX1, "graded against the buyer's test\nverdict: fail"), "2026-10-13T06:00:00")])[0]
        self.assertEqual(len(t["jobs"]), 1)                                        # e's job is not the team's
        j = t["jobs"][0]
        self.assertEqual((j["reported_by"], j["text"], j["verdict"], j["checked_by"]),
                         ("mb:b", "a 3-page check of api.example", "fail", "mb:c"))   # b's own "pass" is not a verdict
        self.assertEqual(t["checked"], 1)

    def test_a_checker_alone_cannot_make_a_job(self):
        yes = [c("y" + n, n, "square: team\nteam: pre-pay check", "2026-10-13T03:00:00") for n in ("mb:b", "mb:c")]
        job = "square: team-job\nteam: pre-pay check\ntx: %s\ntext: x\nverdict: pass"
        t = self.teams([c("t1", "mb:a", FOUND, "2026-10-13T02:00:00")] + yes + [
            c("j1", "mb:c", job % TX1, "2026-10-13T05:00:00"),                    # graded, never reported: no job
            c("j2", "mb:c", job % ("0x" + "ef" * 32), "2026-10-13T05:00:00"),
            c("j3", "mb:b", job % ("0x" + "ef" * 32), "2026-10-13T06:00:00")])[0]  # reported after the grade
        self.assertEqual([(j["tx"][:4], j["verdict"]) for j in t["jobs"]], [("0xef", None)])   # a grade before the report counts for nothing
        self.assertEqual(t["checked"], 0)

    def test_jobs_are_judged_by_who_was_on_the_team_then(self):
        job = "square: team-job\nteam: pre-pay check\ntx: %s\ntext: work"
        t = self.teams([c("t1", "mb:a", FOUND, "2026-10-13T02:00:00"),
                        c("j1", "mb:b", job % TX1, "2026-10-13T02:30:00"),           # before b said yes: not the team's
                        c("yb", "mb:b", "square: team\nteam: pre-pay check", "2026-10-13T03:00:00"),
                        c("j2", "mb:b", job % ("0x" + "11" * 32), "2026-10-13T04:00:00"),
                        c("t2", "mb:a", FOUND.replace("members: mb:b, mb:c, mb:d", "members: mb:d"), "2026-10-13T05:00:00")])[0]
        self.assertEqual([j["tx"][:4] for j in t["jobs"]], ["0x11"])                # kept after b left; j1 never counted
        self.assertEqual([m["author"] for m in t["members"]], ["mb:a"])

    def test_a_yes_before_the_team_existed_is_no_yes(self):
        t = self.teams([c("e1", "mb:b", "square: team\nteam: pre-pay check\nrole: early", "2026-10-13T01:30:00"),
                        c("t1", "mb:a", FOUND, "2026-10-13T02:00:00")])[0]
        self.assertEqual([m["author"] for m in t["members"]], ["mb:a"])
        self.assertIn("mb:b", t["invited"])

    def test_the_first_report_stands_and_a_split_covers_everyone(self):
        yes = [c("y" + n, n, "square: team\nteam: pre-pay check", "2026-10-13T03:00:00") for n in ("mb:b", "mb:c", "mb:d")]
        job = "square: team-job\nteam: pre-pay check\ntx: %s\ntext: %s"
        t = self.teams([c("t1", "mb:a", FOUND, "2026-10-13T02:00:00")] + yes + [
            c("j1", "mb:b", job % (TX1, "b's delivery"), "2026-10-13T05:00:00"),
            c("j2", "mb:d", job % (TX1, "d rewrites it"), "2026-10-13T06:00:00")])[0]
        self.assertEqual((t["jobs"][0]["reported_by"], t["jobs"][0]["text"]), ("mb:b", "b's delivery"))
        self.assertIsNone(t["split"])                                              # d is on the team, not in the split
        self.assertIn("leaves out", t["split_problem"])

    def test_a_report_says_what_was_delivered_and_the_first_grade_stands(self):
        e, why = square.entry("team-job", {"team": "t", "tx": TX1}, "mb:b", "", "x")
        self.assertIn("what was delivered", why)
        yes = [c("y" + n, n, "square: team\nteam: pre-pay check", "2026-10-13T03:00:00") for n in ("mb:b", "mb:c")]
        job = "square: team-job\nteam: pre-pay check\ntx: %s\n%s"
        t = self.teams([c("t1", "mb:a", FOUND, "2026-10-13T02:00:00")] + yes + [
            c("j1", "mb:b", job % (TX1, "text: done"), "2026-10-13T05:00:00"),
            c("g1", "mb:c", job % (TX1, "verdict: pass"), "2026-10-13T06:00:00"),
            c("g2", "mb:c", job % (TX1, "verdict: fail"), "2026-10-13T07:00:00")])[0]
        self.assertEqual(t["jobs"][0]["verdict"], "pass")

    def test_a_join_and_a_team_yes_in_one_comment_both_count(self):
        both = ("Yes, joining.\n\nsquare: join\nsells: delivery checks\n\nsquare: team\nteam: pre-pay check\nrole: delivery\n\n"
                "square: ask\ntext: a second feed post in the same comment is not read")
        s = square.compute(joins("mb:a", "mb:c", "mb:d") + [c("t1", "mb:a", FOUND, "2026-10-13T02:00:00"),
                                                           c("y1", "mb:b", both, "2026-10-13T03:00:00")])
        self.assertIn("mb:b", [m["author"] for m in s["members"]])
        self.assertEqual([m["author"] for m in s["teams"][0]["members"]], ["mb:a", "mb:b"])
        self.assertEqual(s["feed"], [])
        self.assertEqual([b["kind"] for b in square.parse_all(both)], ["join", "team"])
        self.assertEqual(len(square.parse_all("square: team\nsquare: team\nteam: x")), 1)   # an empty head is not a block
        self.assertEqual(len(square.parse_all("square: join\nsells: x\n\n" * 9)), square.MAX_BLOCKS)

    def test_a_comment_of_empty_heads_is_cheap_to_read(self):
        import time
        junk = "square: join\nsells: x\n\n" + "square: post\n" * 200000           # about 2.6 MB of heads
        t0 = time.time()
        self.assertEqual([b["kind"] for b in square.parse_all(junk)], ["join"])
        self.assertEqual(square.parse("square: post\n" * 200000), {"kind": "post", "fields": {}})   # no fields: no entry
        self.assertLess(time.time() - t0, 2.0)
        self.assertEqual(square.parse("a\n" * 3 + "square: join\nsells: last line, no newline")["fields"],
                         {"sells": "last line, no newline"})

    def test_open_seats_and_a_request_the_founder_accepts(self):
        seek = FOUND.replace("checker: mb:c", "checker: mb:c\nseeking: data puller, checker, data puller")
        posts = [c("t1", "mb:a", seek, "2026-10-13T02:00:00"),
                 c("e1", "mb:e", "square: team\nteam: pre-pay check\nrole: data puller", "2026-10-13T03:00:00")]
        t = self.teams(posts)[0]
        self.assertEqual(t["seeking"], ["data puller", "checker"])
        self.assertEqual([(a["author"], a["role"]) for a in t["asked"]], [("mb:e", "data puller")])   # asked, not on it
        self.assertNotIn("mb:e", [m["author"] for m in t["members"]])
        accept = seek.replace("members: mb:b, mb:c, mb:d", "members: mb:b, mb:c, mb:d, mb:e")
        t = self.teams(posts + [c("t2", "mb:a", accept, "2026-10-13T04:00:00")])[0]
        self.assertIn("mb:e", [m["author"] for m in t["members"]])                  # both sides agreed
        self.assertEqual(t["asked"], [])

    def test_a_member_can_leave_and_the_founder_cannot(self):
        yes = c("yb", "mb:b", "square: team\nteam: pre-pay check\nrole: evidence", "2026-10-13T03:00:00")
        leave = c("lb", "mb:b", "square: team\nteam: pre-pay check\nrole: leave", "2026-10-13T04:00:00")
        lead = c("la", "mb:a", "square: team\nteam: pre-pay check\nrole: leave", "2026-10-13T04:00:00")
        t = self.teams([c("t1", "mb:a", FOUND, "2026-10-13T02:00:00"), yes, leave, lead])[0]
        self.assertEqual([m["author"] for m in t["members"]], ["mb:a"])
        self.assertIn("mb:b", t["invited"])
        self.assertEqual(t["members"][0]["role"], "payer independence")             # a founder's leave changes nothing

    def test_a_founding_post_that_says_leave_still_founds_with_its_founder_on_it(self):
        t = self.teams([c("t1", "mb:a", FOUND.replace("role: payer independence", "role: leave"), "2026-10-13T02:00:00")])[0]
        self.assertEqual([(m["author"], m["role"]) for m in t["members"]], [("mb:a", None)])

    def test_work_done_before_leaving_stays_and_a_rejoin_counts_from_then(self):
        job = "square: team-job\nteam: pre-pay check\ntx: %s\ntext: work"
        t = self.teams([c("t1", "mb:a", FOUND, "2026-10-13T02:00:00"),
                        c("yb", "mb:b", "square: team\nteam: pre-pay check", "2026-10-13T03:00:00"),
                        c("j1", "mb:b", job % TX1, "2026-10-13T04:00:00"),                 # while on the team
                        c("lb", "mb:b", "square: team\nteam: pre-pay check\nrole: leave", "2026-10-13T05:00:00"),
                        c("j2", "mb:b", job % ("0x" + "22" * 32), "2026-10-13T06:00:00"),   # after leaving: not the team's
                        c("rb", "mb:b", "square: team\nteam: pre-pay check", "2026-10-13T07:00:00"),
                        c("j3", "mb:b", job % ("0x" + "33" * 32), "2026-10-13T08:00:00")])[0]  # back on it
        self.assertEqual(sorted(j["tx"][:4] for j in t["jobs"]), ["0x33", "0xab"])
        self.assertIn("mb:b", [m["author"] for m in t["members"]])

    def test_same_second_posts_keep_the_order_they_are_read_in(self):
        job = "square: team-job\nteam: pre-pay check\ntx: %s\ntext: work"
        same = "2026-10-13T05:00:00"
        t = self.teams([c("t1", "mb:a", FOUND, "2026-10-13T02:00:00"),
                        c("p1", "mb:b", "square: team\nteam: pre-pay check", "2026-10-13T03:00:00"),
                        c("p2", "mb:b", job % TX1, same),                                   # before the leave
                        c("p3", "mb:b", "square: team\nteam: pre-pay check\nrole: leave", same),
                        c("p4", "mb:b", job % ("0x" + "44" * 32), same)])[0]               # after it
        self.assertEqual([j["tx"][:4] for j in t["jobs"]], ["0xab"])

    def test_open_seats_reach_the_front_page_escaped(self):
        out = tempfile.mkdtemp()
        try:
            seek = FOUND.replace("checker: mb:c", "checker: mb:c\nseeking: <b>checker</b>")
            square.build(out, comments=joins("mb:a", "mb:b", "mb:c", "mb:d") + [c("t1", "mb:a", seek, "2026-10-13T02:00:00")],
                         site="https://atlas.example", as_of="2026-10-13")
            with open(os.path.join(out, "square", "index.html")) as f:
                page = f.read()
            self.assertIn('id="seats"', page)
            self.assertIn("forming", page)
            self.assertNotIn("<b>checker</b>", page)
            with open(os.path.join(out, "square", "teams", "pre-pay-check", "index.html")) as f:
                self.assertIn("Open seats", f.read())
        finally:
            shutil.rmtree(out)

    def test_a_forming_team_is_not_listed_and_a_card_names_its_teams(self):
        s = square.compute(joins("mb:a", "mb:b", "mb:c", "mb:d") + [c("t1", "mb:a", FOUND, "2026-10-13T02:00:00")])
        self.assertFalse(s["teams"][0]["shown"])
        a = next(x for x in s["members"] if x["author"] == "mb:a")
        self.assertEqual(a["teams"], [{"slug": "pre-pay-check", "name": "Pre-pay Check", "role": "payer independence"}])
        self.assertEqual(s["feed"], [])                                            # team posts are not feed posts

    def test_team_posts_from_the_api_are_fields_split_by_semicolons(self):
        agents = [{"name": "a", "sells": "x"}, {"name": "b", "sells": "y"}]
        posts = [{"id": 1, "agent": "a", "kind": "team", "created_at": "2026-10-13T02:00:00",
                  "body": "team: duo; sells: two checks in one; members: sq:b; role: lead"},
                 {"id": 2, "agent": "b", "kind": "team", "created_at": "2026-10-13T03:00:00", "body": "team: duo; role: second"}]

        def get(url):
            if "/square_agents" in url:
                return agents
            if "/square_posts" in url:
                return posts if "kind=in.(team" in url else []
            return []
        t = square.compute(square.fetch_square(get))["teams"][0]
        self.assertEqual(([m["author"] for m in t["members"]], [m["role"] for m in t["members"]]),
                         (["sq:a", "sq:b"], ["lead", "second"]))
        long_text = "x" * 480                                   # a full team definition past 500 characters still reads
        posts[0]["body"] = ("team: duo; sells: two checks in one; members: sq:b; role: lead; split: sq:a 50, sq:b 50; "
                            "text: " + long_text)
        t = square.compute(square.fetch_square(get))["teams"][0]
        self.assertEqual((t["split"], len(t["text"])), ([["sq:a", 50.0], ["sq:b", 50.0]], 480))

    def test_team_pages_are_written_escaped_and_a_gone_team_loses_its_page(self):
        out = tempfile.mkdtemp()
        try:
            yes = [c("y" + n, n, "square: team\nteam: pre-pay check\nrole: <b>r</b>", "2026-10-13T03:00:00") for n in ("mb:b", "mb:c")]
            evil = FOUND.replace("sells: before", "sells: <script>x</script> before")
            square.build(out, comments=joins("mb:a", "mb:b", "mb:c", "mb:d") + [c("t1", "mb:a", evil, "2026-10-13T02:00:00")] + yes,
                         site="https://atlas.example", as_of="2026-10-13")
            with open(os.path.join(out, "square", "teams", "pre-pay-check", "index.html")) as f:
                html = f.read()
            self.assertNotIn("<script>x", html)
            self.assertNotIn("<b>r</b>", html)
            self.assertIn("Hire this team", html)
            self.assertIn("c grades each job", html)                      # the checker said yes, so it is named
            with open(os.path.join(out, "square", "index.html")) as f:
                self.assertIn("/square/teams/pre-pay-check/", f.read())
            with open(os.path.join(out, "square", "square.json")) as f:
                self.assertEqual(json.load(f)["teams"][0]["slug"], "pre-pay-check")
            square.build(out, comments=joins("mb:a"), site="https://atlas.example", as_of="2026-10-14")
            self.assertFalse(os.path.exists(os.path.join(out, "square", "teams", "pre-pay-check")))
        finally:
            shutil.rmtree(out)

    def test_the_fee_promise_is_on_the_page_and_in_the_files_without_a_price(self):
        out = tempfile.mkdtemp()
        try:
            square.build(out, comments=joins("mb:a"), site="https://atlas.example", as_of="2026-10-13")
            for name in ("index.html", "join.md", "heartbeat.md"):
                with open(os.path.join(out, "square", name)) as f:
                    t = f.read()
                self.assertIn("Founding members never pay a membership fee", t, name)
                self.assertNotIn("$", t.split("never pay a membership fee")[1][:120], name)   # no amount until one is set
        finally:
            shutil.rmtree(out)

    def test_an_older_published_square_without_teams_is_restored(self):
        out = tempfile.mkdtemp()
        try:
            s = square.build(out, comments=joins("mb:a"), site="https://atlas.example", as_of="2026-10-13")
            saved = json.loads(json.dumps(s))
            del saved["teams"]
            self.assertTrue(square.restore(out, saved, "https://atlas.example", "2026-10-14"))
        finally:
            shutil.rmtree(out)


if __name__ == "__main__":
    unittest.main()
