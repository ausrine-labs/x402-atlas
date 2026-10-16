#!/usr/bin/env python3
"""square_refresh.py — /square/ alone, rewritten into a copy of the published site.

    square_refresh.py --out _site [--changed-against URL --changed-file FILE]

Run by .github/workflows/square.yml every quarter hour, so a post or a wallet proof shows within
fifteen minutes instead of at the next morning's build. Everything outside /square/ is left exactly
as the morning build wrote it. The Square is built from the same inputs as the morning build: the
newest snapshot and the on-chain window that build published in the site itself (radar/ and
flows/), plus the Square's own sources. It is a quick build (square.build quick=True): a wallet the
live Square proved, with the same route, is not asked again, so a member's route is not called
every quarter hour; the morning build checks every wallet again. A source that cannot be read
writes the last published Square again, as the morning build does.

With --changed-against, the new square.json is compared with the one live at URL, its build time
aside, and `changed=1` or `changed=0` is appended to --changed-file (the workflow's output). Most
quarter hours nothing on the Square changes, and then nothing is published.
"""
import argparse
import glob
import gzip
import json
import os
import shutil
import sys
import tempfile
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import radar  # noqa: E402
import seller_pages  # noqa: E402
import square  # noqa: E402


def unpack(src, dst, prefix):
    """Every <prefix>-*.json.gz the morning build published in `src`, unzipped into `dst`; their count."""
    os.makedirs(dst, exist_ok=True)
    n = 0
    for f in sorted(glob.glob(os.path.join(src, prefix + "-*.json.gz"))):
        with gzip.open(f, "rb") as i, open(os.path.join(dst, os.path.basename(f)[:-3]), "wb") as o:
            shutil.copyfileobj(i, o)
        n += 1
    return n


def refresh(out, work):
    """The Square written into `out`; returns its state, or None when nothing could be written."""
    if not os.path.isdir(os.path.join(out, "square")):
        sys.exit("square-refresh: %s holds no published Square to rewrite" % out)
    store, flows = os.path.join(work, "store"), os.path.join(work, "flows")
    if not unpack(os.path.join(out, "radar"), store, "market"):
        sys.exit("square-refresh: no snapshot under %s/radar" % out)
    radar.STORE = store
    new = radar.load_snapshot(radar.snapshots()[-1])
    A = new["sellers"]
    flows_dir = flows if unpack(os.path.join(out, "flows"), flows, "flows") else None
    as_of, foot, n = new["date"], seller_pages.FOOT, len(A)
    rooms = os.path.join(out, "square", "rooms")
    if os.path.isdir(rooms) and not os.path.islink(rooms):   # the morning's rooms never go out again as if new
        shutil.rmtree(rooms)
    try:
        s = square.build(out, flows_dir, A, seller_pages.SITE, as_of, foot=foot, n=n, quick=True)
    except Exception as e:  # noqa: BLE001 - remote, untrusted input: as in seller_pages.build_square
        print("square: not rebuilt (%s: %s)" % (type(e).__name__, e))
        s = None
    if s is not None:
        print("square: %d members, %d posts" % (len(s["members"]), len(s["feed"])))
        return s
    print("square: a source could not be read; the last published Square is written again")
    saved = square.published_square()
    if saved and square.restore(out, saved, seller_pages.SITE, as_of, foot=foot, n=n):
        return saved
    return None


LIVE_ROOMS = ("https://atlas.infoharmoni.com/square/rooms/index.html", "https://atlas.infoharmoni.com/square/rooms/rooms.json")


def keep_live_rooms(out, urls=LIVE_ROOMS, get=None):
    """When the rooms could not be rebuilt, the rooms as published now are carried into the deploy, so a refresh
    neither rolls notes back nor leaves the page missing. True when they were carried."""
    d = os.path.join(out, "square", "rooms")
    if os.path.exists(os.path.join(d, "rooms.json")):
        return False
    try:
        got = {}
        for u in urls:
            if get is None:
                with urllib.request.urlopen(urllib.request.Request(u, headers={"Cache-Control": "no-cache"}), timeout=30) as r:
                    got[u.rsplit("/", 1)[1]] = r.read(20_000_000)
            else:
                got[u.rsplit("/", 1)[1]] = get(u)
        json.loads(got["rooms.json"])                       # a real rooms file, or nothing is written
    except Exception as e:  # noqa: BLE001 - nothing live to keep: the next refresh tries again
        print("square: the live rooms could not be kept (%s)" % type(e).__name__)
        return False
    os.makedirs(d, exist_ok=True)
    for name, body in got.items():
        with open(os.path.join(d, name), "wb") as f:
            f.write(body)
    print("square: the rooms could not be rebuilt; the live rooms are kept as published")
    return True


def _content(d):
    """square.json without its build time: what decides whether there is anything new to publish."""
    d = dict(d)
    now = dict(d.get("now") or {})
    now.pop("as_of", None)
    d["now"] = now
    return json.dumps(d, sort_keys=True)


def changed(out, live_url, get=None):
    """False only when the Square just written in `out` matches the one live at `live_url`, its build
    time aside. Anything that can't be read counts as changed: a deploy too many is harmless."""
    try:
        with open(os.path.join(out, "square", "square.json")) as f:
            new = json.load(f)
        if get is None:
            with urllib.request.urlopen(urllib.request.Request(live_url, headers={"Cache-Control": "no-cache"}),
                                        timeout=30) as r:
                body = r.read(20_000_000)
        else:
            body = get(live_url)
        if _content(new) != _content(json.loads(body)):
            return True
        return rooms_changed(out, live_url.rsplit("/", 1)[0] + "/rooms/rooms.json", get)
    except Exception as e:  # noqa: BLE001 - a failed comparison publishes
        print("square: could not compare with the live Square (%s); publishing" % type(e).__name__)
        return True


def rooms_changed(out, live_url, get=None):
    """Whether the rooms' notes differ from the live ones (a new note changes no member card, so square.json alone would
    miss it). No rooms written here: nothing to publish for them. Live rooms that can't be read: publish."""
    path = os.path.join(out, "square", "rooms", "rooms.json")
    if not os.path.exists(path):
        return False
    with open(path) as f:
        new = json.load(f).get("notes")
    try:
        if get is None:
            with urllib.request.urlopen(urllib.request.Request(live_url, headers={"Cache-Control": "no-cache"}),
                                        timeout=30) as r:
                body = r.read(20_000_000)
        else:
            body = get(live_url)
        return json.dumps(new, sort_keys=True) != json.dumps(json.loads(body).get("notes"), sort_keys=True)
    except Exception as e:  # noqa: BLE001 - a failed comparison publishes
        print("square: could not compare with the live rooms (%s); publishing" % type(e).__name__)
        return True


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, help="the published site, unpacked")
    ap.add_argument("--changed-against", default=None, help="the live square.json, to publish only when it differs")
    ap.add_argument("--changed-file", default=None, help="where to append changed=1 or changed=0 (GITHUB_OUTPUT)")
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as work:
        if refresh(a.out, work) is None:
            sys.exit("square-refresh: the Square could be neither built nor restored; nothing to publish")
    keep_live_rooms(a.out)
    if a.changed_against and a.changed_file:
        c = changed(a.out, a.changed_against)
        print("square: %s" % ("changed since the live Square; publishing" if c else "nothing new since the live Square"))
        with open(a.changed_file, "a") as f:
            f.write("changed=%d\n" % (1 if c else 0))


if __name__ == "__main__":
    main()
