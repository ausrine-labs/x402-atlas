"""Tests for square_refresh.py: the quarter-hour Square rewrites /square/ and nothing else."""
import gzip
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import square  # noqa: E402
import square_refresh  # noqa: E402


def gz(path, obj):
    with gzip.open(path, "wt") as f:
        json.dump(obj, f)


class Refresh(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = os.path.join(self.tmp.name, "_site")
        for d in ("square", "radar", "flows", "s/example.com"):
            os.makedirs(os.path.join(self.out, d))
        gz(os.path.join(self.out, "radar", "market-2026-10-14.json.gz"), {"date": "2026-10-14", "sellers": {"old.example": {}}})
        gz(os.path.join(self.out, "radar", "market-2026-10-15.json.gz"),
           {"date": "2026-10-15", "sellers": {"a.example": {}, "b.example": {}}})
        gz(os.path.join(self.out, "flows", "flows-2026-10-14.json.gz"), {"day": "2026-10-14"})
        gz(os.path.join(self.out, "flows", "whales-2026-10-15.json.gz"), {})
        with open(os.path.join(self.out, "s/example.com/index.html"), "w") as f:
            f.write("the morning build's page")
        self.calls = []
        self.real = square.build

        def fake(out, flows_dir, A, site, as_of, foot=None, n=None, quick=False):
            self.calls.append({"flows": sorted(os.listdir(flows_dir)) if flows_dir else None, "A": sorted(A),
                               "as_of": as_of, "n": n, "quick": quick})
            with open(os.path.join(out, "square", "index.html"), "w") as f:
                f.write("new square")
            return {"members": [], "feed": []}
        square.build = fake

    def tearDown(self):
        square.build = self.real
        self.tmp.cleanup()

    def run_refresh(self):
        with tempfile.TemporaryDirectory() as work:
            return square_refresh.refresh(self.out, work)

    def test_builds_from_the_newest_published_snapshot_and_window(self):
        self.assertIsNotNone(self.run_refresh())
        c = self.calls[0]
        self.assertEqual(c["as_of"], "2026-10-15")
        self.assertEqual(c["A"], ["a.example", "b.example"])
        self.assertEqual(c["n"], 2)
        self.assertEqual(c["flows"], ["flows-2026-10-14.json"])      # the rollups are not the window
        self.assertTrue(c["quick"])                                  # proven wallets are not asked every quarter hour

    def test_rewrites_only_the_square(self):
        self.run_refresh()
        with open(os.path.join(self.out, "square", "index.html")) as f:
            self.assertEqual(f.read(), "new square")
        with open(os.path.join(self.out, "s/example.com/index.html")) as f:
            self.assertEqual(f.read(), "the morning build's page")
        self.assertEqual(sorted(os.listdir(self.out)), ["flows", "radar", "s", "square"])   # no work files left behind

    def test_no_window_still_builds_the_square(self):
        for f in os.listdir(os.path.join(self.out, "flows")):
            os.remove(os.path.join(self.out, "flows", f))
        self.run_refresh()
        self.assertIsNone(self.calls[0]["flows"])

    def test_refuses_a_site_without_a_square_or_a_snapshot(self):
        os.rmdir(os.path.join(self.out, "square"))
        with self.assertRaises(SystemExit):
            self.run_refresh()
        os.makedirs(os.path.join(self.out, "square"))
        for f in os.listdir(os.path.join(self.out, "radar")):
            os.remove(os.path.join(self.out, "radar", f))
        with self.assertRaises(SystemExit):
            self.run_refresh()
        self.assertEqual(self.calls, [])


class Changed(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.makedirs(os.path.join(self.tmp.name, "square"))
        self.live = {"kind": "square", "now": {"as_of": "2026-10-15T17:46Z", "founding": {"members": ["sq:a"]}},
                     "members": [{"author": "sq:a"}], "feed": []}

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, d):
        with open(os.path.join(self.tmp.name, "square", "square.json"), "w") as f:
            json.dump(d, f)

    def test_only_the_build_time_differs_so_nothing_is_published(self):
        self.write(dict(self.live, now={"as_of": "2026-10-15T18:01Z", "founding": {"members": ["sq:a"]}}))
        self.assertFalse(square_refresh.changed(self.tmp.name, "u", get=lambda u: json.dumps(self.live).encode()))

    def test_a_new_post_or_member_is_published(self):
        self.write(dict(self.live, feed=[{"id": "p1"}]))
        self.assertTrue(square_refresh.changed(self.tmp.name, "u", get=lambda u: json.dumps(self.live).encode()))
        self.write(dict(self.live, now={"as_of": "x", "founding": {"members": ["sq:a", "sq:b"]}}))
        self.assertTrue(square_refresh.changed(self.tmp.name, "u", get=lambda u: json.dumps(self.live).encode()))

    def test_a_live_square_that_cannot_be_read_publishes(self):
        self.write(self.live)

        def down(u):
            raise OSError("down")
        self.assertTrue(square_refresh.changed(self.tmp.name, "u", get=down))
        self.assertTrue(square_refresh.changed(self.tmp.name, "u", get=lambda u: b"<html>not json"))


if __name__ == "__main__":
    unittest.main()
