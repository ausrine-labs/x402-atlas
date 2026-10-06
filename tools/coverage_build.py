#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit f04f064). Edit it there, not here.
"""coverage_build.py — build /live/, /where/, /leaders/ and /prices/ in one go.

    coverage_build.py --whales whales-2026-09-24.json --store radar-store \
                      --flows flows-2026-09-*.json [--settlements settlements-2026-09-24.json] \
                      [--dbip-cache ~/.cache/dbip | --dbip file.csv.gz] --out _site [--full]

Since 2026-10-05 the pages are built in the free tier (tiers.FREE_TIER_ONLY): TOP rows a
table and the headline figures, the rest said to be in the full record. --full builds
them whole, as before.

The newest registry snapshot in --store gives the sellers; the rollup gives what was
paid. The DB-IP file is downloaded into --dbip-cache when it is not there; if that
fails, /where/ is still built and says no seller could be placed. Nothing here is
deployed. Standard library only.
"""

import argparse
import json
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import leaders  # noqa: E402
import live_feed  # noqa: E402
import prices  # noqa: E402
import tiers  # noqa: E402
import where_hosted  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--whales", required=True)
    ap.add_argument("--store", required=True, help="registry snapshots, market-<date>.json")
    ap.add_argument("--flows", nargs="*", default=[])
    ap.add_argument("--settlements")
    ap.add_argument("--dbip")
    ap.add_argument("--dbip-cache")
    ap.add_argument("--site", default="", help="where the Atlas is served, e.g. https://atlas.infoharmoni.com or "
                    "https://ausrine-labs.github.io/x402-atlas; every page links under its path")
    ap.add_argument("--out", required=True)
    tiers.add_flags(ap)
    a = ap.parse_args()
    free = tiers.from_args(a)
    today = date.today().isoformat()
    rollup = json.load(open(a.whales))
    snaps = sorted(f for f in os.listdir(a.store) if f.startswith("market-") and f.endswith(".json"))
    snap = json.load(open(os.path.join(a.store, snaps[-1])))

    flows = [json.load(open(p)) for p in a.flows]
    base = [f for f in flows if live_feed.base_day(f)]
    newest_base = max(base, key=lambda f: f.get("date") or "") if base else None
    print(live_feed.write(a.out, live_feed.live_data(rollup, snap["sellers"], a.site, newest_base, free=free)))

    dbip = a.dbip
    if not dbip and a.dbip_cache:
        try:
            dbip = where_hosted.fetch_dbip(a.dbip_cache)
        except Exception as e:
            print("where: %s" % e, file=sys.stderr)
    db = where_hosted.CountryDB.load(dbip) if dbip else None
    resolved = where_hosted.resolve_all(snap["sellers"])
    wd = where_hosted.where_data(snap["sellers"], rollup, resolved, db, today, os.path.basename(dbip or ""), a.site, free=free)
    print(where_hosted.write(a.out, wd))

    st = json.load(open(a.settlements)) if a.settlements else None
    ld = leaders.leaders_data(rollup, leaders.load_snapshots(a.store), leaders.load_flow_days(a.flows),
                              st["settlements"] if st else None, st["date"] if st else None, as_of=today, site=a.site,
                              wallet_hosts=leaders.load_wallet_hosts(a.flows), free=free)
    print(leaders.write(a.out, ld))

    pd = prices.prices_data(snap["sellers"], rollup, snap.get("date", ""), today, a.site, free=free)
    print(prices.write(a.out, pd))

    summary = {
        "live": {"seller_wallets": len(live_feed.live_data(rollup, snap["sellers"])["wallets"]),
                 "fallback": live_feed.base_day(newest_base)},
        "where": {k: wd[k] for k in ("hosts", "placed", "behind_cdn", "unresolved", "unplaced", "cdn", "have_db")}
                 | {"countries": [(r["cc"], r["sellers"]) for r in wd["countries"]]},
        "leaders": {"facilitators": None if ld["facilitators"] is None else ld["facilitators"][:3],
                    "new_sellers": ld["new_sellers"][:5], "new_sellers_n": len(ld["new_sellers"]),
                    "new_buyers_n": len(ld["new_buyers"]), "chains": ld["chains"]},
        "prices": [{k: r[k] for k in ("category", "sellers", "p25", "median", "p75", "undercut", "paid_sellers")}
                   for r in pd["categories"]],
    }
    print(json.dumps(summary, indent=1, default=str))


if __name__ == "__main__":
    main()
