#!/usr/bin/env python3
"""square_refresh.py — /square/ alone, rewritten into a copy of the published site.

    square_refresh.py --out _site

Run by .github/workflows/square.yml every quarter hour, so a post or a wallet proof shows within
fifteen minutes instead of at the next morning's build. Everything outside /square/ is left exactly
as the morning build wrote it. The Square is built the way the morning build builds it
(seller_pages.build_square), from the same inputs: the newest snapshot and the on-chain window the
morning build published in the site itself (radar/ and flows/), plus the Square's own sources. A
source that cannot be read writes the last published Square again, as the morning build does.
"""
import argparse
import glob
import gzip
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import radar  # noqa: E402
import seller_pages  # noqa: E402


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
    return seller_pages.build_square(out, flows_dir, A, new["date"], seller_pages.FOOT, len(A))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, help="the published site, unpacked")
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as work:
        if refresh(a.out, work) is None:
            sys.exit("square-refresh: the Square could be neither built nor restored; nothing to publish")


if __name__ == "__main__":
    main()
