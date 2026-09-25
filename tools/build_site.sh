#!/bin/sh
# build_site.sh — the whole public site, from one morning's photograph of the market.
#
# Run by .github/workflows/daily.yml. It keeps NO market data in this repository's
# history: the rolling window lives only on the published site. Each run reads that
# window back (checking every file), adds today, drops what is older than 8 days,
# rebuilds every seller page, and hands the result to GitHub Pages.
set -eu
SITE=https://ausrine-labs.github.io/x402-atlas
rm -rf store flows _site && mkdir -p store flows _site

# 1. yesterday's window, from the live site; from this repo's radar/ only if the site has none
python3 tools/snapshot_handoff.py fetch "$SITE/radar/" --store store || {
  echo "::warning::no published window on the site; seeding from radar/ in the repository"
  for f in radar/market-*.json.gz; do [ -f "$f" ] && gunzip -c "$f" > "store/$(basename "${f%.gz}")"; done
}

# 2. today's photograph. A failed scan is not fatal: the site is rebuilt from the last good day.
RADAR_STORE=store python3 tools/radar.py snapshot || echo "::warning::today's scan failed; rebuilding from the last good day"

# 3. never build from a broken photograph (this registry was once silently truncated)
python3 - <<'PY'
import glob, os, re, sys
sys.path.insert(0, "tools")
import snapshot_handoff as sh
for f in sorted(glob.glob("store/market-*.json")):
    day = re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
    why = sh.check_snapshot(open(f, "rb").read(), day, sh.FLOOR)
    if why:
        print("::warning::dropping %s: %s" % (f, why)); os.remove(f)
if not glob.glob("store/market-*.json"):
    sys.exit("no usable snapshot at all: refusing to deploy an empty site")
PY

# 4. who paid whom, read straight off Base: yesterday's flows window back from the live
#    site, today's pull against the wallets in the newest snapshot, then the whale rollup
#    over the window. Best effort at every step: the pages are built either way.
LATEST=$(ls store/market-*.json | sort | tail -1)
DAY=$(basename "$LATEST" .json | sed 's/^market-//')
python3 tools/flows_handoff.py fetch "$SITE/flows/" --store flows || echo "::warning::no published flows window yet; starting one today"
YESTERDAY=$(date -u -d "$DAY -1 day" +%F)          # the last whole UTC day; pulled by block timestamp, so days tile exactly
python3 tools/chain_flows.py --snapshot "$LATEST" --day "$YESTERDAY" --out "flows/flows-$YESTERDAY.json" || echo "::warning::the chain pull for $YESTERDAY failed; the window keeps what it has"
if ls flows/flows-*.json >/dev/null 2>&1; then
  # one day only: every page says "yesterday", so the rollup is the newest whole day, never the window
  NEWEST=$(ls flows/flows-*.json | sort | tail -1)
  python3 tools/whales.py report --flows "$NEWEST" --snapshot "$LATEST" --top 20 --out "flows/whales-$DAY.json" \
    > "flows/whales-$DAY.txt" || echo "::warning::the whale rollup failed"
fi

# 5. the site
for p in data LICENSE README.md robots.txt *.txt; do [ -e "$p" ] && cp -R "$p" _site/; done
mkdir -p _site/map && cp index.html _site/map/index.html      # the 3D map moves to /map/; seller_pages.py writes the front door at /
python3 tools/snapshot_handoff.py publish --store store --out _site/radar
if [ -f "flows/whales-$DAY.json" ]; then
  python3 tools/seller_pages.py --out _site --store store --whales "flows/whales-$DAY.json"
else
  python3 tools/seller_pages.py --out _site --store store
fi
if ls flows/flows-*.json >/dev/null 2>&1; then
  python3 tools/flows_handoff.py publish --store flows --out _site/flows || echo "::warning::nothing fit to publish under flows/"
  [ -f "flows/whales-$DAY.txt" ] && cp "flows/whales-$DAY.txt" _site/flows/whales-latest.txt
fi
touch _site/.nojekyll
du -sh _site | cut -f1

# 6. tell search engines which pages changed today (IndexNow: a key file on our own site,
#    no account). Best effort: a failure here never fails the build.
python3 - <<'PY' || true
import json, re, urllib.request
site = "https://ausrine-labs.github.io/x402-atlas"
key = open(next(f for f in __import__("os").listdir(".") if re.fullmatch(r"[0-9a-f]{32}\.txt", f))).read().strip()
urls = re.findall(r"<loc>([^<]+)</loc>", open("_site/sitemap-sellers.xml").read())[:10000]
body = json.dumps({"host": "ausrine-labs.github.io", "key": key, "keyLocation": site + "/" + key + ".txt", "urlList": urls}).encode()
req = urllib.request.Request("https://api.indexnow.org/indexnow", data=body, headers={"Content-Type": "application/json; charset=utf-8"})
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        print("indexnow:", r.status, "for", len(urls), "urls")
except Exception as e:
    print("indexnow failed:", type(e).__name__, getattr(e, "code", ""))
PY
