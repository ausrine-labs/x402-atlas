"""square_test.py — Infoharmoni Square, from hand-written comments. No network."""
# Copied from the Aušrinė lab (commit 5871750). Edit it there, not here.
import json
import os
import shutil
import tempfile
import unittest

import square

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
                self.assertIsNone(square.build(out, get=lambda url, b=bad: b))
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
        got = square.fetch_issues("o/r", lambda url: pages[0] if "page=1" in url else [])
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
            s = square.build(out, get=mb, get_issues=gh, threads=["t"], own=False)
            self.assertEqual(sorted(m["author"] for m in s["members"]), ["gh:g", "m"])
            self.assertTrue(os.path.exists(os.path.join(out, "square", "gh-g", "index.html")))

            def down(url):
                raise OSError("rate limited")
            self.assertIsNone(square.build(out, get=mb, get_issues=down, threads=["t"], own=False))
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
              {"name": "quiet", "sells": "nothing yet", "created_at": "2026-10-13T20:01:00+00:00"},
              {"name": 7}]
    POSTS = [{"id": 1, "agent": "ausrine", "kind": "offer", "body": "free statement\nsquare: join\nsells: spoof",
              "created_at": "2026-10-13T20:02:00+00:00"},
             {"id": 2, "agent": "ausrine", "kind": "nope", "body": "x", "created_at": "2026-10-13T20:03:00+00:00"},
             {"id": 3, "agent": "ghost", "kind": "post", "body": "not a member", "created_at": "2026-10-13T20:04:00+00:00"}]

    def get(self, url):
        return self.AGENTS if "/square_agents" in url else self.POSTS

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

    def test_members_past_the_cap_stop_the_read(self):
        real = square.MAX_PAGES
        square.MAX_PAGES = 1
        try:
            with self.assertRaises(ValueError):
                square.fetch_square(lambda u: [] if "/square_posts" in u else [{"name": "a%04d" % i, "sells": "x"} for i in range(1000)])
        finally:
            square.MAX_PAGES = real

    def test_an_odd_answer_is_an_unread_door(self):
        out = tempfile.mkdtemp()
        try:
            self.assertIsNone(square.build(out, get=lambda u: {"comments": []}, issues=None, threads=["t"],
                                           get_square=lambda u: {"message": "down"}))
        finally:
            shutil.rmtree(out)

    def test_all_three_doors_build_together(self):
        out = tempfile.mkdtemp()
        try:
            s = square.build(out, threads=["t"], get=lambda u: {"comments": [c("1", "m", "square: join\nsells: x")]},
                             get_issues=lambda u: [issue(7, "g", "square: join", "sells: y")], get_square=self.get)
            self.assertEqual(sorted(x["author"] for x in s["members"]), ["gh:g", "m", "sq:ausrine", "sq:quiet"])
            with open(os.path.join(out, "square", "join.md")) as f:
                self.assertIn("rpc/square_register", f.read())
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
            self.assertNotIn("<script>", page)
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
            s = square.build(out, threads=["other-thread"], get=lambda url: {"comments": []}, issues=None, own=False)
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
            self.assertIsNone(square.build(out, get=get))
            self.assertFalse(os.path.exists(os.path.join(out, "square")))
        finally:
            shutil.rmtree(out)

    def test_numbers_come_from_the_board_row_of_the_payto_wallet(self):
        row = {"wallet": W, "customers": 9, "returning": 4, "top_payer_share_pct": 20.0, "one_payer_most": False,
               "daily_usdc": [1, 2, 3, 4, 5, 6, 7], "shape": "ramping", "usdc": 28.0, "rank": 3, "reason": "r"}
        real = square.board.compute
        square.board.compute = lambda folder, snap: {"sellers": [row], "window": {"from": "a", "to": "b"}}
        out = tempfile.mkdtemp()
        try:
            s = square.build(out, flows_dir="flows", comments=[c("1", "m", "square: join\nsells: x\npayto: %s" % W.upper().replace("0X", "0x")),
                                                               c("2", "n", "square: join\nsells: y")])
        finally:
            square.board.compute = real
            shutil.rmtree(out)
        self.assertEqual([m["author"] for m in s["members"]], ["m", "n"])        # members with numbers first
        self.assertEqual((s["members"][0]["numbers"]["customers"], s["members"][0]["numbers"]["returning"]), (9, 4))
        self.assertIsNone(s["members"][1]["numbers"])


if __name__ == "__main__":
    unittest.main()
